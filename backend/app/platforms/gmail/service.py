"""Gmail source platform — per-tenant credentials stored in DB.

Each company has its own Gmail OAuth credentials and token,
stored in the integration config (encrypted in the integrations table).

Config structure:
  {
    "label": "invoices",
    "credentials_json": {...},   # The OAuth app credentials (from credentials.json)
    "token_json": {...},         # The OAuth token (generated via authorize flow)
  }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.platforms.base import InvoiceSource, register_source

logger = logging.getLogger(__name__)


@register_source
class GmailSource(InvoiceSource):
    platform_key = "gmail"
    display_name = "Gmail"
    description = "Pull invoices from Gmail labels"
    category = "source"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    def _has_credentials(self) -> bool:
        """Check if OAuth app credentials are stored in config."""
        return bool(self.config.get("credentials_json"))

    def _has_token(self) -> bool:
        """Check if OAuth token is stored in config."""
        return bool(self.config.get("token_json"))

    def _get_gmail_service(self):
        """Build Gmail API service from stored credentials."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_data = self.config.get("token_json")
        if not token_data:
            raise RuntimeError("Gmail OAuth token not configured. Authorize Gmail in Settings.")

        if isinstance(token_data, str):
            token_data = json.loads(token_data)

        creds = Credentials.from_authorized_user_info(token_data)

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Note: updated token should be saved back to DB by the caller

        if not creds.valid:
            raise RuntimeError("Gmail OAuth token expired. Re-authorize in Settings.")

        return build("gmail", "v1", credentials=creds)

    def test_connection(self) -> Dict[str, Any]:
        if not self._has_credentials():
            return {"healthy": False, "message": "Gmail credentials not configured. Upload credentials.json in Settings."}

        if not self._has_token():
            creds_data = self.config.get("credentials_json", {})
            if isinstance(creds_data, str):
                creds_data = json.loads(creds_data)
            key = "installed" if "installed" in creds_data else "web"
            project_id = creds_data.get(key, {}).get("project_id", "unknown")
            return {
                "healthy": False,
                "message": f"Credentials valid (project: {project_id}) but no OAuth token yet.",
                "details": {"project_id": project_id, "token_exists": False},
            }

        # Token exists — try to connect
        try:
            service = self._get_gmail_service()
            profile = service.users().getProfile(userId="me").execute()
            email = profile.get("emailAddress", "unknown")
            total_messages = profile.get("messagesTotal", 0)

            label_name = self.config.get("label", "invoices")
            labels_resp = service.users().labels().list(userId="me").execute()
            labels = labels_resp.get("labels", [])
            label_found = any(l["name"].lower() == label_name.lower() for l in labels)

            return {
                "healthy": True,
                "message": f"Connected to {email}",
                "details": {
                    "email": email,
                    "total_messages": total_messages,
                    "label": label_name,
                    "label_exists": label_found,
                },
            }
        except Exception as e:
            logger.exception("Gmail test_connection failed")
            return {"healthy": False, "message": f"Gmail connection failed: {type(e).__name__}"}

    def fetch_invoices(self, db: Session, since: Optional[datetime] = None) -> Dict[str, Any]:
        """Fetch invoices using per-tenant Gmail credentials from DB."""
        from app.services.email_service import EmailService
        from app.services.draft_service import DraftService

        # Build Gmail service from stored config
        gmail_service = self._get_gmail_service()

        email_service = EmailService(db, gmail_service=gmail_service, label=self.config.get("label", "invoices"))
        fetch_stats = email_service.fetch_and_process()

        draft_service = DraftService(db)
        drafts = draft_service.create_drafts_for_parsed_invoices(source="gmail")

        return {
            "emails_found": fetch_stats["total_found"],
            "new_emails": fetch_stats["new_emails"],
            "invoices_parsed": fetch_stats["invoices_parsed"],
            "drafts_created": len(drafts),
            "errors": fetch_stats["errors"],
        }

    @classmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        return [
            {"key": "label", "label": "Gmail Label to Watch", "type": "text",
             "required": True, "default": "invoices"},
        ]
