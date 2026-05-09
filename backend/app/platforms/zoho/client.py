from __future__ import annotations

import logging
import os

import httpx

from app.core.exceptions import ZohoError, ZohoRateLimitError
from app.core.retry import zoho_retry
from app.platforms.zoho.auth import ZohoAuth

logger = logging.getLogger(__name__)


class ZohoClient:
    """HTTP client for Zoho Books API v3."""

    def __init__(self, auth: ZohoAuth, base_url: str, organization_id: str,
                 default_account_id: str = ""):
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self.org_id = organization_id
        self.default_account_id = default_account_id

    def _headers(self) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {self.auth.get_access_token()}",
            "Content-Type": "application/json",
        }

    def _params(self, extra: dict = None) -> dict:
        params = {"organization_id": self.org_id}
        if extra:
            params.update(extra)
        return params

    def _handle_response(self, response: httpx.Response) -> dict:
        if response.status_code == 429:
            raise ZohoRateLimitError("Rate limit exceeded")
        if response.status_code == 401:
            self.auth.invalidate()
            raise ZohoError("Auth failed. Token invalidated.")
        if response.status_code >= 400:
            try:
                msg = response.json().get("message", response.text)
            except Exception:
                msg = response.text
            raise ZohoError(f"Zoho API error ({response.status_code}): {msg}")
        return response.json()

    @zoho_retry
    def create_bill(self, payload: dict) -> dict:
        url = f"{self.base_url}/bills"
        resp = httpx.post(url, headers=self._headers(), params=self._params(), json=payload, timeout=30)
        return self._handle_response(resp)

    @zoho_retry
    def get_bill(self, bill_id: str) -> dict:
        url = f"{self.base_url}/bills/{bill_id}"
        resp = httpx.get(url, headers=self._headers(), params=self._params(), timeout=30)
        return self._handle_response(resp)

    @zoho_retry
    def delete_bill(self, bill_id: str) -> dict:
        url = f"{self.base_url}/bills/{bill_id}"
        resp = httpx.delete(url, headers=self._headers(), params=self._params(), timeout=30)
        return self._handle_response(resp)

    @zoho_retry
    def list_contacts(self, contact_name: str = None, contact_type: str = "vendor") -> list:
        url = f"{self.base_url}/contacts"
        extra = {"contact_type": contact_type}
        if contact_name:
            extra["contact_name"] = contact_name
        resp = httpx.get(url, headers=self._headers(), params=self._params(extra), timeout=30)
        return self._handle_response(resp).get("contacts", [])

    @zoho_retry
    def create_contact(self, payload: dict) -> dict:
        url = f"{self.base_url}/contacts"
        resp = httpx.post(url, headers=self._headers(), params=self._params(), json=payload, timeout=30)
        return self._handle_response(resp)

    @zoho_retry
    def find_bill_by_number(self, bill_number: str) -> dict | None:
        """Search for an existing bill by bill_number (for deduplication)."""
        url = f"{self.base_url}/bills"
        resp = httpx.get(url, headers=self._headers(),
                         params=self._params({"bill_number": bill_number}), timeout=30)
        data = self._handle_response(resp)
        bills = data.get("bills", [])
        for b in bills:
            if b.get("bill_number") == bill_number:
                return b
        return None

    def attach_document(self, bill_id: str, file_path: str) -> dict:
        """Attach a file to a Zoho bill via multipart/form-data.

        Attachment failure should be caught by the caller — bill is already created.
        """
        url = f"{self.base_url}/bills/{bill_id}/attachment"
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Zoho-oauthtoken {self.auth.get_access_token()}"},
                params=self._params(),
                files={"attachment": (file_name, f, "application/octet-stream")},
                timeout=60,
            )
        return self._handle_response(resp)

    @zoho_retry
    def list_tds_taxes(self) -> list:
        """Fetch TDS tax records from Zoho Books (India edition).

        Endpoint: GET /settings/taxes?is_tds_request=true. With this flag Zoho
        returns rows scoped to TDS (Direct Taxes → Income TDS Rates), each with
        tax_type='tds_tax'. Without the flag the same endpoint returns GST taxes.
        """
        url = f"{self.base_url}/settings/taxes"
        resp = httpx.get(
            url, headers=self._headers(),
            params=self._params({"is_tds_request": "true"}),
            timeout=30,
        )
        return self._handle_response(resp).get("taxes", [])

    def list_chartofaccounts(self) -> list:
        """Fetch all Chart of Accounts from Zoho Books with pagination."""
        url = f"{self.base_url}/chartofaccounts"
        all_accounts = []
        page = 1
        while True:
            resp = httpx.get(
                url, headers=self._headers(),
                params=self._params({"page": page, "per_page": 200}),
                timeout=30,
            )
            data = self._handle_response(resp)
            accounts = data.get("chartofaccounts", [])
            all_accounts.extend(accounts)
            if not data.get("page_context", {}).get("has_more_page", False):
                break
            page += 1
        return all_accounts
