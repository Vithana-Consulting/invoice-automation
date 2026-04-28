from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


class ChargebeeClient:
    """HTTP client for Chargebee API v2."""

    def __init__(self, site: str, api_key: str):
        self.base_url = f"https://{site}.chargebee.com/api/v2"
        self.api_key = api_key

    def _auth(self) -> tuple:
        return (self.api_key, "")

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            try:
                err = resp.json().get("message", resp.text)
            except Exception:
                err = resp.text
            raise Exception(f"Chargebee API error ({resp.status_code}): {err}")
        return resp.json()

    def list_invoices(self, limit: int = 100, offset: str = None,
                      updated_after: int = None) -> dict:
        params: Dict[str, Any] = {"limit": limit}
        if offset:
            params["offset"] = offset
        if updated_after:
            params["updated_at[after]"] = updated_after
        resp = httpx.get(f"{self.base_url}/invoices", auth=self._auth(),
                        params=params, timeout=30)
        return self._handle(resp)

    def get_invoice(self, invoice_id: str) -> dict:
        resp = httpx.get(f"{self.base_url}/invoices/{invoice_id}",
                        auth=self._auth(), timeout=15)
        return self._handle(resp)
