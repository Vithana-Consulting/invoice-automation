"""Google Drive client — per-tenant credentials stored in DB.

Config structure (stored in integrations table, platform='google_drive'):
  {
    "credentials_json": {...},   # OAuth app credentials
    "token_json": {...},         # OAuth token with drive.file scope
    "parent_folder_id": "...",   # Optional root folder ID for this tenant
  }

Folder structure created under parent_folder_id:
  /{year}/{vendor_name}/{filename}
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]


class DriveClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.parent_folder_id: Optional[str] = config.get("parent_folder_id") or None

    def _build_service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_data = self.config.get("token_json")
        if not token_data:
            raise RuntimeError("Google Drive OAuth token not configured.")
        if isinstance(token_data, str):
            token_data = json.loads(token_data)

        creds = Credentials.from_authorized_user_info(token_data)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds.valid:
            raise RuntimeError("Google Drive OAuth token invalid. Re-authorize in Settings.")

        return build("drive", "v3", credentials=creds)

    def _find_or_create_folder(self, service, name: str, parent_id: Optional[str] = None) -> str:
        """Return the folder ID for `name` under `parent_id`, creating it if absent."""
        query_parts = [
            "mimeType = 'application/vnd.google-apps.folder'",
            f"name = '{name}'",
            "trashed = false",
        ]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")

        results = service.files().list(
            q=" and ".join(query_parts),
            fields="files(id, name)",
            spaces="drive",
        ).execute()

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        metadata: Dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = service.files().create(body=metadata, fields="id").execute()
        return folder["id"]

    def upload_file(self, file_path: str, year: str, vendor_name: str) -> Dict[str, str]:
        """Upload file_path to Drive under /{year}/{vendor_name}/.

        Returns {"file_id": "...", "web_view_link": "..."}.
        Raises RuntimeError on auth/config problems, IOError on file problems.
        """
        from googleapiclient.http import MediaFileUpload

        service = self._build_service()

        # Build folder path: parent → year → vendor_name
        year_folder_id = self._find_or_create_folder(service, str(year), self.parent_folder_id)
        safe_vendor = _safe_folder_name(vendor_name)
        vendor_folder_id = self._find_or_create_folder(service, safe_vendor, year_folder_id)

        file_name = os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        file_metadata: Dict[str, Any] = {
            "name": file_name,
            "parents": [vendor_folder_id],
        }
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=False)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        logger.info("Uploaded %s to Drive (id=%s)", file_name, uploaded.get("id"))
        return {
            "file_id": uploaded.get("id", ""),
            "web_view_link": uploaded.get("webViewLink", ""),
        }


def _safe_folder_name(name: str) -> str:
    """Remove characters not allowed in Drive folder names."""
    if not name:
        return "Unknown Vendor"
    safe = name.replace("/", "-").replace("\\", "-").strip()
    return safe[:100] or "Unknown Vendor"
