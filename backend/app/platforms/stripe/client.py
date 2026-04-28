from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

STRIPE_API_BASE = "https://api.stripe.com/v1"


class StripeClient:
    """HTTP client for Stripe API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                err = resp.text
            raise Exception(f"Stripe API error ({resp.status_code}): {err}")
        return resp.json()

    def get_balance(self) -> dict:
        resp = httpx.get(f"{STRIPE_API_BASE}/balance", headers=self._headers(), timeout=15)
        return self._handle(resp)

    def list_invoices(self, limit: int = 100, starting_after: str = None,
                      created_gte: int = None) -> dict:
        params: Dict[str, Any] = {"limit": limit}
        if starting_after:
            params["starting_after"] = starting_after
        if created_gte:
            params["created[gte]"] = created_gte
        resp = httpx.get(f"{STRIPE_API_BASE}/invoices", headers=self._headers(),
                        params=params, timeout=30)
        return self._handle(resp)

    def get_invoice(self, invoice_id: str) -> dict:
        resp = httpx.get(f"{STRIPE_API_BASE}/invoices/{invoice_id}",
                        headers=self._headers(), timeout=15)
        return self._handle(resp)
