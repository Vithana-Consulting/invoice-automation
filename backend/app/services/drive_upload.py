"""Shared helper for uploading invoice files to Google Drive.

Controlled by the STORAGE_BACKEND setting:
  local        — files stay on disk only (default)
  google_drive — files are also uploaded to the tenant's Google Drive

Best-effort: any failure logs a warning and returns None, never raises.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def try_drive_upload(file_path: str, invoice_record, db: Session) -> Optional[str]:
    """Upload file_path to Google Drive if STORAGE_BACKEND=google_drive.

    Returns the Drive file_id on success, None otherwise.
    """
    from app.config import settings

    if settings.STORAGE_BACKEND != "google_drive":
        return None

    try:
        from app.db.repository import IntegrationRepository
        from app.platforms.base import decrypt_config
        from app.platforms.google_drive.client import DriveClient

        repo = IntegrationRepository(db)
        integration = repo.get_by_platform("google_drive")
        if not integration or not integration.is_enabled:
            logger.warning("STORAGE_BACKEND=google_drive but no google_drive integration configured for this tenant")
            return None

        config = decrypt_config(integration.config_encrypted)
        client = DriveClient(config)

        year = _extract_year(invoice_record)
        vendor = (getattr(invoice_record, "vendor_name", None) or "Unknown Vendor").strip()

        result = client.upload_file(file_path, year, vendor)
        return result.get("file_id") or None

    except Exception as exc:
        logger.warning("Drive upload failed for %s: %s", file_path, exc)
        return None


def _extract_year(invoice_record) -> str:
    date_str = getattr(invoice_record, "invoice_date", None) or ""
    if date_str and len(date_str) >= 4:
        return date_str[:4]
    from datetime import datetime
    return str(datetime.utcnow().year)
