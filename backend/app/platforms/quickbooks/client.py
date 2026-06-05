from __future__ import annotations

import logging
import time
from threading import Lock

import httpx

logger = logging.getLogger(__name__)


def _escape_qbo_query_literal(value: str) -> str:
    """Escape a string for safe use inside a QuickBooks query string literal.

    QBO's query language wraps literals in single quotes and escapes embedded
    apostrophes with a backslash (e.g. ``WHERE DisplayName = 'Adam\\'s Shop'``).
    Backslashes are doubled first so they can't break the escape sequence.
    See Intuit's data-queries docs.
    """
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


class QuickBooksAuth:
    """OAuth2 token manager for QuickBooks Online."""

    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires_at: float = 0
        self._lock = Lock()

    def get_access_token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at - 60:
                return self._access_token
            return self._refresh()

    def _refresh(self) -> str:
        resp = httpx.post(self.TOKEN_URL, auth=(self.client_id, self.client_secret), data={
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        if "refresh_token" in data:
            self.refresh_token = data["refresh_token"]
        return self._access_token


class QuickBooksClient:
    """HTTP client for QuickBooks Online API."""

    def __init__(self, auth: QuickBooksAuth, realm_id: str,
                 base_url: str = "https://quickbooks.api.intuit.com"):
        self.auth = auth
        self.realm_id = realm_id
        self.base_url = f"{base_url}/v3/company/{realm_id}"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            try:
                err = resp.json()
                msg = err.get("Fault", {}).get("Error", [{}])[0].get("Detail", resp.text)
            except Exception:
                msg = resp.text
            raise Exception(f"QuickBooks API error ({resp.status_code}): {msg}")
        return resp.json()

    def get_company_info(self) -> dict:
        resp = httpx.get(f"{self.base_url}/companyinfo/{self.realm_id}",
                        headers=self._headers(), timeout=15)
        return self._handle(resp)

    def create_bill(self, payload: dict) -> dict:
        resp = httpx.post(f"{self.base_url}/bill", headers=self._headers(),
                         json=payload, timeout=30)
        return self._handle(resp)

    def query(self, query_str: str) -> dict:
        resp = httpx.get(f"{self.base_url}/query",
                        headers=self._headers(),
                        params={"query": query_str}, timeout=15)
        return self._handle(resp)

    def find_vendor(self, name: str) -> list:
        safe = _escape_qbo_query_literal(name)
        result = self.query(f"SELECT * FROM Vendor WHERE DisplayName = '{safe}'")
        return result.get("QueryResponse", {}).get("Vendor", [])

    def create_vendor(self, display_name: str) -> dict:
        resp = httpx.post(f"{self.base_url}/vendor", headers=self._headers(),
                         json={"DisplayName": display_name}, timeout=15)
        return self._handle(resp)
