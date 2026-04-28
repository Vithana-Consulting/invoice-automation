"""Per-tenant Google OAuth2 helpers.

Each company has its own Google OAuth credentials stored as an integration
(platform="google_oauth"). The login flow encodes company_id in the state
parameter (signed JWT) so the callback knows which company to authenticate against.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
import jwt

from app.config import settings
from app.models.db_models import Integration
from app.platforms.base import decrypt_config

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _get_company_oauth_config(company_id: int, db) -> dict:
    """Load Google OAuth config for a company from integrations table.

    Raises ValueError if not configured.
    """
    integration = (
        db.query(Integration)
        .filter(Integration.company_id == company_id, Integration.platform == "google_oauth")
        .first()
    )
    if not integration:
        raise ValueError(f"Google OAuth not configured for company {company_id}")
    config = decrypt_config(integration.config_encrypted)
    if not config.get("client_id") or not config.get("client_secret"):
        raise ValueError(f"Google OAuth credentials incomplete for company {company_id}")
    return config


def sign_oauth_state(company_id: int) -> str:
    """Create a signed JWT state parameter containing company_id.

    Used to securely pass company context through the OAuth redirect.
    Short-lived (5 minutes) to prevent replay.
    """
    payload = {
        "company_id": company_id,
        "exp": datetime.utcnow() + timedelta(minutes=5),
        "iat": datetime.utcnow(),
        "type": "oauth_state",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_oauth_state(state: str) -> int:
    """Verify and decode the OAuth state JWT. Returns company_id.

    Raises jwt.InvalidTokenError if tampered or expired.
    """
    payload = jwt.decode(state, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "oauth_state":
        raise jwt.InvalidTokenError("Invalid state token type")
    return payload["company_id"]


def get_google_auth_url(company_id: int, db) -> str:
    """Build the Google OAuth2 authorization URL for a specific company."""
    config = _get_company_oauth_config(company_id, db)
    state = sign_oauth_state(company_id)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config.get("redirect_uri", settings.GOOGLE_REDIRECT_URI),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


async def exchange_code_for_tokens(company_id: int, code: str, db) -> dict:
    """Exchange authorization code for Google tokens using company's credentials."""
    config = _get_company_oauth_config(company_id, db)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": config.get("redirect_uri", settings.GOOGLE_REDIRECT_URI),
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_google_user_info(access_token: str) -> dict:
    """Fetch user info from Google using access token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def create_jwt_token(user_id: int) -> str:
    """Create a JWT token for the authenticated user."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
