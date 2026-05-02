from __future__ import annotations

import logging
import time
from threading import Lock

import httpx

from app.core.exceptions import ZohoAuthError

logger = logging.getLogger(__name__)


class ZohoAuth:
    """Thread-safe Zoho OAuth2 token manager.

    Instantiated per-request from DB config. Not a singleton.
    """

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 auth_url: str = "https://accounts.zoho.in/oauth/v2/token"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.auth_url = auth_url
        self._access_token: str | None = None
        self._expires_at: float = 0
        self._lock = Lock()

    def get_access_token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at - 120:
                return self._access_token
            # Rate-limit protection: don't refresh more than once per 30 seconds
            if hasattr(self, '_last_refresh') and time.time() - self._last_refresh < 30:
                if self._access_token:
                    return self._access_token
            return self._refresh()

    def _refresh(self) -> str:
        if not self.client_id or not self.refresh_token:
            raise ZohoAuthError("Zoho credentials incomplete. Update in Integrations.")
        try:
            response = httpx.post(self.auth_url, data={
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            }, timeout=30)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            # Log full response for debugging, expose only status code to caller
            logger.error("Zoho token refresh failed: HTTP %d — %s", e.response.status_code, e.response.text[:500])
            raise ZohoAuthError(f"Token refresh failed: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error("Zoho token refresh error: %s", e)
            raise ZohoAuthError(f"Token refresh failed: {type(e).__name__}")

        if "access_token" not in data:
            raise ZohoAuthError(f"Missing access_token: {data}")

        self._access_token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        self._last_refresh = time.time()
        logger.info("Zoho access token refreshed")
        return self._access_token

    def invalidate(self):
        with self._lock:
            self._access_token = None
            self._expires_at = 0

    @staticmethod
    def exchange_code(
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        auth_url: str = "https://accounts.zoho.in/oauth/v2/token",
    ) -> dict:
        """Exchange a Zoho grant code for access + refresh tokens.

        Returns the full token response dict (contains refresh_token).
        Raises ZohoAuthError on failure.
        """
        try:
            resp = httpx.post(auth_url, data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("Zoho code exchange failed: HTTP %d — %s", e.response.status_code, e.response.text[:500])
            raise ZohoAuthError(f"Code exchange failed: HTTP {e.response.status_code} — {e.response.text[:200]}")
        except Exception as e:
            raise ZohoAuthError(f"Code exchange failed: {e}")

        if "refresh_token" not in data:
            raise ZohoAuthError(f"No refresh_token in response: {data}")

        return data
