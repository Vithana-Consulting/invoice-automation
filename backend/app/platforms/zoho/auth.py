from __future__ import annotations

import logging
import time
from threading import Lock

import httpx

from app.config import settings
from app.core.exceptions import ZohoAuthError
from app.core.key_pool import KeyExhaustedError, get_key_pool, run_with_rotation

logger = logging.getLogger(__name__)

DEFAULT_AUTH_URL = "https://accounts.zoho.in/oauth/v2/token"


class ZohoAuth:
    """Thread-safe Zoho OAuth2 token manager with credential-set failover.

    Instantiated per-request from DB config. Not a singleton.

    A single set of credentials (``client_id`` / ``client_secret`` /
    ``refresh_token``) works exactly as before. To enable failover, pass
    ``credentials`` — a list of credential-set dicts. When a token refresh
    fails (auth error, rate limit, network), the pool parks the failing set in
    a cooldown window and rotates to the next set, so a single revoked or
    throttled Zoho app never breaks a push during the demo.
    """

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 auth_url: str = DEFAULT_AUTH_URL,
                 credentials: list[dict] | None = None,
                 pool_name: str = "zoho"):
        # Normalise to a list of credential sets. The top-level args remain the
        # first/primary set for backward compatibility.
        if credentials:
            self._creds = [self._norm(c, auth_url) for c in credentials if c.get("client_id")]
        else:
            self._creds = []
        primary = self._norm(
            {"client_id": client_id, "client_secret": client_secret,
             "refresh_token": refresh_token, "auth_url": auth_url},
            auth_url,
        )
        if primary["client_id"] and not any(
            c["client_id"] == primary["client_id"] for c in self._creds
        ):
            self._creds.insert(0, primary)

        # Pool key = client_id of each set (masked when logged/exposed).
        self._by_key = {c["client_id"]: c for c in self._creds}
        self._pool = get_key_pool(
            pool_name, ",".join(self._by_key.keys()),
            cooldown_seconds=settings.KEY_POOL_COOLDOWN_SECONDS,
        )

        self._access_token: str | None = None
        self._expires_at: float = 0
        self._active_key: str | None = None
        self._last_refresh: float = 0
        self._lock = Lock()

    @staticmethod
    def _norm(c: dict, default_auth_url: str) -> dict:
        return {
            "client_id": c.get("client_id", ""),
            "client_secret": c.get("client_secret", ""),
            "refresh_token": c.get("refresh_token", ""),
            "auth_url": c.get("auth_url") or default_auth_url,
        }

    def get_access_token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at - 120:
                return self._access_token
            # Rate-limit protection: don't refresh more than once per 30 seconds
            if self._last_refresh and time.time() - self._last_refresh < 30:
                if self._access_token:
                    return self._access_token
            try:
                return run_with_rotation(self._pool, self._refresh_with)
            except KeyExhaustedError as e:
                raise ZohoAuthError(f"All Zoho credential sets are failing: {e}")

    def _refresh_with(self, key: str) -> str:
        """Refresh the access token using the credential set identified by ``key``.

        Called by ``run_with_rotation`` — raises on failure so the pool rotates
        to the next set. Must be invoked with ``self._lock`` already held.
        """
        cred = self._by_key.get(key)
        if not cred or not cred["client_id"] or not cred["refresh_token"]:
            raise ZohoAuthError("Zoho credentials incomplete. Update in Integrations.")
        try:
            response = httpx.post(cred["auth_url"], data={
                "refresh_token": cred["refresh_token"],
                "client_id": cred["client_id"],
                "client_secret": cred["client_secret"],
                "grant_type": "refresh_token",
            }, timeout=30)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            # Log full response for debugging, expose only status code to caller
            logger.error("Zoho token refresh failed: HTTP %d — %s",
                         e.response.status_code, e.response.text[:500])
            raise ZohoAuthError(f"Token refresh failed: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error("Zoho token refresh error: %s", e)
            raise ZohoAuthError(f"Token refresh failed: {type(e).__name__}")

        if "access_token" not in data:
            raise ZohoAuthError(f"Missing access_token: {data}")

        self._access_token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        self._active_key = key
        self._last_refresh = time.time()
        logger.info("Zoho access token refreshed")
        return self._access_token

    def invalidate(self):
        """Drop the cached token and park the active credential set.

        Called on HTTP 401 — the credential that produced the token is bad, so
        we park it in the pool's cooldown and force the next call to rotate.
        """
        with self._lock:
            if self._active_key:
                self._pool.report_failure(self._active_key, "HTTP 401 — token rejected")
            self._access_token = None
            self._expires_at = 0
            self._active_key = None

    @staticmethod
    def exchange_code(
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        auth_url: str = DEFAULT_AUTH_URL,
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
