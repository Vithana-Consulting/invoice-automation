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
from app.services.invoice_service import InvoiceService

logger = logging.getLogger(__name__)

MIME_TYPE_MAP = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/tiff": "tiff",
    "image/bmp": "bmp",
}


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
        """Fetch emails labeled as invoices from Gmail, download attachments, and parse."""
        # Use injected per-tenant service, or fall back to legacy file-based auth
        service = self._gmail_service or self._get_gmail_service()
        label = self.label

        label_id = self._find_label_id(service, label)
        if not label_id:
            raise EmailFetchError(f"Gmail label '{label}' not found")

        results = (
            service.users()
            .messages()
            .list(userId="me", labelIds=[label_id], maxResults=50)
            .execute()
        )
        messages = results.get("messages", [])

        stats = {
            "total_found": len(messages),
            "new_emails": 0,
            "skipped_existing": 0,
            "attachments_downloaded": 0,
            "invoices_parsed": 0,
            "errors": [],
        }

        for msg_ref in messages:
            msg_id = msg_ref["id"]
            if self.email_repo.exists(msg_id):
                stats["skipped_existing"] += 1
                continue
            try:
                self._process_message(service, msg_id, stats)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg_id, e)
                stats["errors"].append({"message_id": msg_id, "error": str(e)})

        logger.info(
            "Email fetch complete: %d new, %d skipped, %d attachments, %d parsed",
            stats["new_emails"], stats["skipped_existing"],
            stats["attachments_downloaded"], stats["invoices_parsed"],
        )
        return stats

    def _find_label_id(self, service, label_name: str) -> str | None:
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        for lbl in labels:
            if lbl["name"].lower() == label_name.lower():
                return lbl["id"]
        return None

    def _process_message(self, service, msg_id: str, stats: dict):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

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
        msg_dir = os.path.join(settings.ATTACHMENT_DIR, msg_id)
        os.makedirs(msg_dir, exist_ok=True)

        invoice_service = InvoiceService(self.db)

        for att in attachments:
            try:
                file_path = self._download_attachment(service, msg_id, att, msg_dir)
                stats["attachments_downloaded"] += 1

                sha = hashlib.sha256()
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha.update(chunk)
                content_hash = sha.hexdigest()

                existing = self.invoice_repo.get_by_content_hash(content_hash)
                if existing:
                    logger.info("Duplicate attachment: %s", att["filename"])
                    continue

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

    def _download_attachment(self, service, msg_id: str, att: dict, dest_dir: str) -> str:
        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=msg_id, id=att["attachment_id"])
            .execute()
        )
        data = base64.urlsafe_b64decode(attachment["data"])
        file_path = os.path.join(dest_dir, att["filename"])
        with open(file_path, "wb") as f:
            f.write(data)
        logger.info("Downloaded attachment: %s (%d bytes)", att["filename"], len(data))
        return file_path
