from __future__ import annotations

import logging

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
    def list_chartofaccounts(self) -> list:
        """Fetch all accounts from Zoho Books Chart of Accounts."""
        url = f"{self.base_url}/chartofaccounts"
        resp = httpx.get(url, headers=self._headers(), params=self._params(), timeout=30) # AI_RECOMMENDATION : What if there are 10k COA? batch fetch 50 per batch
        return self._handle_response(resp).get("chartofaccounts", [])
