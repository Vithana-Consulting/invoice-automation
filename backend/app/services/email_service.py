from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import EmailFetchError
from app.db.repository import AuditLogRepository, EmailRepository, InvoiceRepository
from app.models.db_models import InvoiceRecord, ProcessedEmail
from app.services import attachment_storage
from app.services.invoice_service import InvoiceService
from app.services.drive_upload import try_drive_upload
from app.tenant.context import TenantContext

logger = logging.getLogger(__name__)

MIME_TYPE_MAP = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/tiff": "tiff",
    "image/bmp": "bmp",
    # Word documents — converted to PDF before parsing (convert-then-parse).
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
}

# Bound the label scan (coding standard #6 — list queries bounded).
# 200 messages/page * 25 pages = 5000 messages max per run; remainder picked up next run.
MAX_LIST_PAGES = 25


class EmailService:
    def __init__(self, db: Session, gmail_service=None, label: str = None):
        """Initialize with optional pre-built Gmail service (per-tenant).

        Args:
            db: Database session
            gmail_service: Pre-authenticated Gmail API service (from per-tenant config).
                          If None, falls back to file-based credentials (legacy).
            label: Gmail label to watch. Defaults to settings.GMAIL_LABEL.
        """
        self.db = db
        self.label = label or settings.GMAIL_LABEL
        self._gmail_service = gmail_service  # Injected per-tenant service
        self.email_repo = EmailRepository(db)
        self.invoice_repo = InvoiceRepository(db)
        self.audit_repo = AuditLogRepository(db)

    def _get_gmail_service(self):
        """Authenticate and return Gmail API service."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise EmailFetchError(
                "Google API libraries not installed. "
                "Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )

        scopes = [settings.GMAIL_SCOPES]
        creds = None

        if os.path.exists(settings.GMAIL_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(
                settings.GMAIL_TOKEN_FILE, scopes
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(settings.GMAIL_CREDENTIALS_FILE):
                    raise EmailFetchError(
                        f"Gmail credentials file not found: {settings.GMAIL_CREDENTIALS_FILE}. "
                        "Download it from Google Cloud Console -> APIs & Services -> Credentials."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.GMAIL_CREDENTIALS_FILE, scopes
                )
                creds = flow.run_local_server(port=0)

            with open(settings.GMAIL_TOKEN_FILE, "w") as token:
                token.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def fetch_and_process(self) -> dict:
        """Fetch invoice-labeled threads from Gmail, download attachments from
        every message in each thread, and parse.

        Works at the THREAD level: each label hit is expanded to its whole thread,
        so invoices sent as *replies* within a parent thread are ingested even
        when the reply message itself doesn't carry the watched label.
        """
        # Use injected per-tenant service, or fall back to legacy file-based auth
        service = self._gmail_service or self._get_gmail_service()
        label = self.label

        label_id = self._find_label_id(service, label)
        if not label_id:
            raise EmailFetchError(f"Gmail label '{label}' not found")

        # Walk all label pages, collecting unique thread ids (bounded — std #6).
        thread_ids: List[str] = []
        seen_threads: set[str] = set()
        total_messages = 0
        page_token = None
        pages = 0
        while True:
            results = (
                service.users()
                .messages()
                .list(userId="me", labelIds=[label_id], maxResults=200, pageToken=page_token)
                .execute()
            )
            refs = results.get("messages", [])
            total_messages += len(refs)
            for msg_ref in refs:
                tid = msg_ref.get("threadId", msg_ref["id"])
                if tid not in seen_threads:
                    seen_threads.add(tid)
                    thread_ids.append(tid)
            page_token = results.get("nextPageToken")
            pages += 1
            if not page_token:
                break
            if pages >= MAX_LIST_PAGES:
                logger.warning(
                    "Gmail label '%s' exceeded %d pages (%d threads so far); stopping "
                    "pagination — remaining messages picked up next run.",
                    label, MAX_LIST_PAGES, len(thread_ids),
                )
                break

        stats = {
            "total_found": total_messages,
            "threads_found": len(thread_ids),
            "new_emails": 0,
            "skipped_existing": 0,
            "attachments_downloaded": 0,
            "invoices_parsed": 0,
            "errors": [],
        }

        for thread_id in thread_ids:
            try:
                self._process_thread(service, thread_id, stats)
            except Exception as e:
                logger.error("Error processing thread %s: %s", thread_id, e)
                stats["errors"].append({"thread_id": thread_id, "error": str(e)})

        logger.info(
            "Email fetch complete: %d threads, %d new, %d skipped, %d attachments, %d parsed",
            stats["threads_found"], stats["new_emails"], stats["skipped_existing"],
            stats["attachments_downloaded"], stats["invoices_parsed"],
        )
        return stats

    def _process_thread(self, service, thread_id: str, stats: dict):
        """Fetch a full thread and process every message in it.

        ``threads().get(format='full')`` returns full payloads (incl. attachment
        ids) for all messages, so no extra per-message GET is needed. Already-seen
        messages are skipped via ``email_repo.exists``, so re-running a thread only
        handles new replies.
        """
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
        for msg in thread.get("messages", []):
            msg_id = msg["id"]
            if self.email_repo.exists(msg_id):
                stats["skipped_existing"] += 1
                continue
            try:
                self._process_message(service, msg, thread_id, stats)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg_id, e)
                stats["errors"].append({"message_id": msg_id, "error": str(e)})

    def _find_label_id(self, service, label_name: str) -> str | None:
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        for lbl in labels:
            if lbl["name"].lower() == label_name.lower():
                return lbl["id"]
        return None

    def _process_message(self, service, msg: dict, thread_id: str, stats: dict):
        """Process one already-fetched full message dict (from threads().get)."""
        msg_id = msg["id"]

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "")
        date_str = headers.get("Date", "")

        received_at = None
        if date_str:
            try:
                received_at = parsedate_to_datetime(date_str)
            except Exception:
                pass

        attachments = self._find_attachments(msg["payload"])

        email_record = ProcessedEmail(
            message_id=msg_id,
            thread_id=thread_id,
            subject=subject[:500],
            sender=sender[:255],
            received_at=received_at,
            attachment_count=len(attachments),
            status="FETCHED",
        )
        email_record = self.email_repo.create(email_record)
        stats["new_emails"] += 1

        self.audit_repo.log(
            entity_type="email",
            entity_id=email_record.id,
            action="email_fetched",
            details={"subject": subject, "attachments": len(attachments)},
        )

        if not attachments:
            self.email_repo.update_status(email_record.id, "COMPLETED")
            return

        self.email_repo.update_status(email_record.id, "PROCESSING")
        company_id = TenantContext.get_optional()

        invoice_service = InvoiceService(self.db)

        for att in attachments:
            try:
                data = self._fetch_attachment_bytes(service, msg_id, att)
                stats["attachments_downloaded"] += 1

                content_hash = hashlib.sha256(data).hexdigest()

                existing = self.invoice_repo.get_by_content_hash(content_hash)
                if existing:
                    logger.info("Duplicate attachment: %s", att["filename"])
                    continue

                # save() routes to local disk or S3 depending on STORAGE_BACKEND;
                # subdir=msg_id preserves the pre-existing local directory layout.
                file_path = attachment_storage.save(company_id, att["filename"], data, subdir=msg_id)
                logger.info("Saved attachment: %s (%d bytes)", att["filename"], len(data))

                ext = os.path.splitext(att["filename"])[1].lower().lstrip(".")
                invoice_record = InvoiceRecord(
                    email_id=email_record.id,
                    file_path=file_path,
                    file_name=att["filename"],
                    file_type=ext,
                    content_hash=content_hash,
                    parsing_status="PENDING",
                    source="gmail",
                )
                invoice_record = self.invoice_repo.create(invoice_record)

                drive_file_id = try_drive_upload(file_path, invoice_record, self.db)
                if drive_file_id:
                    self.invoice_repo._update(invoice_record.id, drive_file_id=drive_file_id)

                if invoice_service.parse_invoice(invoice_record.id):
                    stats["invoices_parsed"] += 1

            except Exception as e:
                logger.error("Error processing attachment %s: %s", att.get("filename"), e)
                stats["errors"].append({"filename": att.get("filename"), "error": str(e)})

        self.email_repo.update_status(email_record.id, "COMPLETED")

    def _find_attachments(self, payload: dict) -> List[dict]:
        attachments = []
        if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
            mime = payload.get("mimeType", "")
            if mime in MIME_TYPE_MAP:
                attachments.append({
                    "filename": payload["filename"],
                    "attachment_id": payload["body"]["attachmentId"],
                    "mime_type": mime,
                })
        for part in payload.get("parts", []):
            attachments.extend(self._find_attachments(part))
        return attachments

    def _fetch_attachment_bytes(self, service, msg_id: str, att: dict) -> bytes:
        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=msg_id, id=att["attachment_id"])
            .execute()
        )
        return base64.urlsafe_b64decode(attachment["data"])


def redownload_invoice_from_gmail(invoice, db) -> str | None:
    """Re-download an invoice PDF from Gmail when the local file no longer exists.

    Extracts the Gmail message ID from the stored file_path directory name
    (structure: data/attachments/{msg_id}/{filename}), fetches the message,
    finds the matching attachment, and saves it back to the original path.

    Returns the local file path on success, None if re-download is not possible.
    """
    try:
        from app.db.repository import IntegrationRepository
        from app.platforms.base import decrypt_config
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not invoice or not invoice.file_path or invoice.source != "gmail":
            return None

        # Extract msg_id from path: data/attachments/{msg_id}/{filename}
        parts = invoice.file_path.replace("\\", "/").split("/")
        # Find the segment just before the filename (the msg_id directory)
        if len(parts) < 2:
            return None
        msg_id = parts[-2]
        file_name = parts[-1]

        if not msg_id or msg_id in ("attachments", "data"):
            return None

        # Load Gmail credentials for this tenant
        repo = IntegrationRepository(db)
        integration = repo.get_by_platform("gmail")
        if not integration or not integration.is_enabled:
            logger.warning("Gmail integration not configured — cannot re-download %s", invoice.file_name)
            return None

        config = decrypt_config(integration.config_encrypted)
        token_data = config.get("token_json")
        if not token_data:
            return None
        if isinstance(token_data, str):
            import json
            token_data = json.loads(token_data)

        creds = Credentials.from_authorized_user_info(token_data)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds.valid:
            logger.warning("Gmail OAuth token invalid — cannot re-download %s", invoice.file_name)
            return None

        service = build("gmail", "v1", credentials=creds)

        # Fetch the message and find the attachment matching file_name
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        att_id = _find_attachment_id(msg.get("payload", {}), file_name)
        if not att_id:
            logger.warning("Attachment %s not found in Gmail message %s", file_name, msg_id)
            return None

        attachment = service.users().messages().attachments().get(
            userId="me", messageId=msg_id, id=att_id
        ).execute()
        data = base64.urlsafe_b64decode(attachment["data"])

        # Restore to original path (local path or s3:// URI, unchanged either way)
        dest = invoice.file_path if attachment_storage.is_remote(invoice.file_path) else os.path.abspath(invoice.file_path)
        attachment_storage.write_bytes(dest, data)

        logger.info("Re-downloaded %s from Gmail message %s (%d bytes)", file_name, msg_id, len(data))
        return dest

    except Exception as exc:
        logger.warning("Gmail re-download failed for invoice %s: %s", getattr(invoice, "id", "?"), exc)
        return None


def _find_attachment_id(payload: dict, filename: str) -> str | None:
    """Recursively search Gmail message parts for an attachment matching filename."""
    if payload.get("filename") == filename and payload.get("body", {}).get("attachmentId"):
        return payload["body"]["attachmentId"]
    for part in payload.get("parts", []):
        result = _find_attachment_id(part, filename)
        if result:
            return result
    return None
