"""User settings and per-tenant Gmail credential management.

Gmail credentials (credentials.json and OAuth token) are stored
in the integration config per company — not on the filesystem.
This ensures multi-tenant isolation.
"""
from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import settings
from app.db.repository import IntegrationRepository
from app.db.session import get_db
from app.models.db_models import User
from app.platforms.base import decrypt_config, encrypt_config

logger = logging.getLogger(__name__)
router = APIRouter()

def _get_gmail_oauth_redirect() -> str:
    """Build Gmail OAuth redirect URI from system config (DB)."""
    from app.db.system_config import sysconfig
    redirect_uri = sysconfig.get("GOOGLE_REDIRECT_URI")
    base_url = redirect_uri.split("/api/")[0]
    return f"{base_url}/api/settings/gmail-callback"


def _get_gmail_config(db: Session) -> dict:
    """Get the Gmail integration config from DB for the current tenant."""
    repo = IntegrationRepository(db)
    integration = repo.get_by_platform("gmail")
    if not integration:
        return {}
    return decrypt_config(integration.config_encrypted)


def _save_gmail_config(db: Session, config: dict):
    """Save Gmail config to the integration table for the current tenant."""
    repo = IntegrationRepository(db)
    integration = repo.get_by_platform("gmail")
    if integration:
        repo.update(integration.id, config_encrypted=encrypt_config(config))
    else:
        repo.create(
            platform="gmail",
            display_name="Gmail",
            config_encrypted=encrypt_config(config),
            is_enabled=True,
        )


@router.get("")
async def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return current user settings, company info, and Gmail credential status."""
    from app.models.db_models import Company
    from app.tenant.context import TenantContext

    gmail_config = _get_gmail_config(db)
    has_creds = bool(gmail_config.get("credentials_json"))
    has_token = bool(gmail_config.get("token_json"))
    gmail_label = gmail_config.get("label", settings.GMAIL_LABEL)

    # Get company info (GST/PAN)
    company_data = {}
    company_id = TenantContext.get_optional()
    if company_id:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            company_data = {
                "id": company.id,
                "name": company.name,
                "domain": company.domain,
                "gst_number": company.gst_number,
                "pan_number": company.pan_number,
            }

    return {
        "status": "success",
        "data": {
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "picture_url": user.picture_url,
            },
            "company": company_data,
            "gmail": {
                "credentials_uploaded": has_creds,
                "token_exists": has_token,
                "label": gmail_label,
            },
        },
    }


@router.put("/company")
async def update_company_settings(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update company settings (GST, PAN). Accessible by authenticated users."""
    from app.models.db_models import Company
    from app.tenant.context import TenantContext

    company_id = TenantContext.get_optional()
    if not company_id:
        raise HTTPException(status_code=403, detail="No company context")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if "gst_number" in body:
        company.gst_number = body["gst_number"].strip().upper() if body["gst_number"] else None
    if "pan_number" in body:
        company.pan_number = body["pan_number"].strip().upper() if body["pan_number"] else None

    db.commit()
    db.refresh(company)
    return {
        "status": "success",
        "data": {
            "gst_number": company.gst_number,
            "pan_number": company.pan_number,
        },
    }


@router.post("/gmail-credentials")
async def upload_gmail_credentials(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload Gmail API credentials.json — stored per-tenant in DB, not filesystem."""
    content = await file.read()

    try:
        creds_data = json.loads(content)
        if "installed" not in creds_data and "web" not in creds_data:
            return {
                "status": "error",
                "message": "Invalid credentials.json — must contain 'installed' or 'web' key.",
            }
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON file"}

    # Store in integration config (DB, per-tenant)
    gmail_config = _get_gmail_config(db)
    gmail_config["credentials_json"] = creds_data
    _save_gmail_config(db, gmail_config)

    logger.info("Gmail credentials uploaded by user %s (%s)", user.id, user.email)
    return {"status": "success", "message": "Gmail credentials uploaded", "data": {"credentials_uploaded": True}}


@router.delete("/gmail-credentials")
async def delete_gmail_credentials(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove Gmail credentials and token for this tenant."""
    gmail_config = _get_gmail_config(db)
    gmail_config.pop("credentials_json", None)
    gmail_config.pop("token_json", None)
    _save_gmail_config(db, gmail_config)

    logger.info("Gmail credentials removed by user %s (%s)", user.id, user.email)
    return {"status": "success", "message": "Gmail credentials removed"}


@router.get("/gmail-authorize")
async def gmail_authorize(db: Session = Depends(get_db)):
    """Start Gmail OAuth flow using per-tenant credentials from DB."""
    from google_auth_oauthlib.flow import Flow

    gmail_config = _get_gmail_config(db)
    creds_data = gmail_config.get("credentials_json")
    if not creds_data:
        return {"status": "error", "message": "Upload credentials.json first"}

    if isinstance(creds_data, str):
        creds_data = json.loads(creds_data)

    # Write temp file for Flow (it requires a file path)
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(creds_data, tmp)
    tmp.close()

    try:
        flow = Flow.from_client_secrets_file(
            tmp.name,
            scopes=[settings.GMAIL_SCOPES],
            redirect_uri=_get_gmail_oauth_redirect(),
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        # Store code_verifier in Gmail config (per-tenant, not filesystem)
        gmail_config["_oauth_state"] = {
            "code_verifier": flow.code_verifier,
            "state": state,
        }
        _save_gmail_config(db, gmail_config)

    finally:
        os.unlink(tmp.name)

    return RedirectResponse(url=auth_url)


@router.get("/gmail-callback")
async def gmail_callback(code: str = Query(...), db: Session = Depends(get_db)):
    """Handle Gmail OAuth callback — store token per-tenant in DB."""
    from google_auth_oauthlib.flow import Flow

    gmail_config = _get_gmail_config(db)
    creds_data = gmail_config.get("credentials_json")
    if not creds_data:
        return {"status": "error", "message": "Gmail credentials not found"}

    if isinstance(creds_data, str):
        creds_data = json.loads(creds_data)

    # Write temp file for Flow
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(creds_data, tmp)
    tmp.close()

    try:
        flow = Flow.from_client_secrets_file(
            tmp.name,
            scopes=[settings.GMAIL_SCOPES],
            redirect_uri=_get_gmail_oauth_redirect(),
        )

        # Restore code verifier from per-tenant config
        oauth_state = gmail_config.get("_oauth_state", {})
        flow.code_verifier = oauth_state.get("code_verifier")

        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Store token in integration config (DB, per-tenant)
        gmail_config["token_json"] = json.loads(creds.to_json())
        gmail_config.pop("_oauth_state", None)  # Clean up temp state
        _save_gmail_config(db, gmail_config)

        logger.info("Gmail OAuth token saved for tenant")

    finally:
        os.unlink(tmp.name)

    return RedirectResponse(url=settings.FRONTEND_URL + "/settings?gmail=connected")


# ─── System Config (Google OAuth — app-level) ─────────────────────────────


@router.get("/system-config")
async def get_system_config(user: User = Depends(get_current_user)):
    """Get system-level config (Google OAuth). Visible to all authenticated users."""
    from app.db.system_config import sysconfig
    return {"status": "success", "data": sysconfig.list_all()}


@router.put("/system-config")
async def update_system_config(body: dict, user: User = Depends(get_current_user)):
    """Update system-level config (Google OAuth).

    Body: {"GOOGLE_CLIENT_ID": "...", "GOOGLE_CLIENT_SECRET": "...", "GOOGLE_REDIRECT_URI": "..."}
    """
    from app.db.system_config import sysconfig, SYSTEM_KEYS
    updated, errors = [], []
    for key, value in body.items():
        if key.upper() not in SYSTEM_KEYS:
            errors.append(f"{key} is not a valid system config key")
            continue
        sysconfig.set(key.upper(), value)
        updated.append(key.upper())
    return {"status": "success", "data": {"updated": updated, "errors": errors}}


# ─── Runtime Config (Parser, LLM — app-level) ─────────────────────────────


@router.get("/runtime-config")
async def get_runtime_config(user: User = Depends(get_current_user)):
    """Get runtime config (parser, LLM settings)."""
    from app.config import _load_overrides, EDITABLE_KEYS, SECRET_KEYS, Settings

    overrides = _load_overrides()
    base = Settings()
    items = []
    for key in sorted(EDITABLE_KEYS):
        env_val = getattr(base, key, "")
        current = overrides.get(key, env_val)
        is_secret = key in SECRET_KEYS
        items.append({
            "key": key,
            "value": (current[:4] + "****" + current[-4:]) if is_secret and current and len(str(current)) > 8 else ("****" if is_secret and current else str(current or "")),
            "is_secret": is_secret,
            "is_overridden": key in overrides,
        })
    return {"status": "success", "data": items}


@router.put("/runtime-config")
async def update_runtime_config(body: dict, user: User = Depends(get_current_user)):
    """Update runtime config. Changes apply without restart."""
    from app.config import _load_overrides, _save_overrides, EDITABLE_KEYS, READONLY_KEYS

    overrides = _load_overrides()
    updated, errors = [], []
    for key, value in body.items():
        upper = key.upper()
        if upper in READONLY_KEYS:
            errors.append(f"{upper} is read-only")
            continue
        if upper not in EDITABLE_KEYS:
            errors.append(f"{upper} is not editable")
            continue
        overrides[upper] = value
        updated.append(upper)
    if updated:
        _save_overrides(overrides)
    return {"status": "success", "data": {"updated": updated, "errors": errors}}


@router.delete("/runtime-config/{key}")
async def reset_runtime_config(key: str, user: User = Depends(get_current_user)):
    """Reset a runtime config key to its .env value."""
    from app.config import _load_overrides, _save_overrides

    overrides = _load_overrides()
    upper = key.upper()
    if upper in overrides:
        del overrides[upper]
        _save_overrides(overrides)
    return {"status": "success", "message": f"{upper} reset to default"}
