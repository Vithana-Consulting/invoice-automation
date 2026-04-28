from __future__ import annotations

import logging
import os
import re
import shutil
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import (
    EDITABLE_KEYS,
    READONLY_KEYS,
    SECRET_KEYS,
    Settings,
    _load_overrides,
    _save_overrides,
    settings,
)
from app.db.session import get_db
from app.models.db_models import (
    AuditLog, Company, CompanyMember, Integration,
    InvoiceDraft, InvoiceRecord, PlatformVendor,
    ProcessedEmail, Rule, User, VendorCache, VendorMapping,
)
from app.platforms.base import decrypt_config, encrypt_config
from app.tenant.views import create_company_views, drop_company_views

logger = logging.getLogger(__name__)
router = APIRouter()

FLUSH_TABLES = [
    "invoice_drafts",
    "invoices",
    "processed_emails",
    "vendor_cache",
    "audit_log",
    "rules",
    "vendor_mappings",
    "platform_vendors",
]


def _verify_admin_key(x_admin_key: str = Header(...)):
    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY not configured in .env")
    if x_admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")


def _mask_value(key: str, value) -> str:
    """Mask secret values for display."""
    if key in SECRET_KEYS and value:
        s = str(value)
        if len(s) > 8:
            return s[:4] + "****" + s[-4:]
        return "****"
    return str(value) if value is not None else ""


class AdminLoginRequest(BaseModel):
    admin_key: str


# ── Admin Login ──────────────────────────────────────────────────────────

@router.post("/login")
def admin_login(body: AdminLoginRequest):
    """Validate admin key and return a session token."""
    key = body.admin_key
    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY not configured")
    if key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return {"status": "success", "data": {"authenticated": True}}


# ── Company CRUD ──────────────────────────────────────────────────────────


class CompanyCreateRequest(BaseModel):
    name: str
    domain: str  # email domain (e.g., "acme.com")


class CompanyOAuthRequest(BaseModel):
    client_id: str
    client_secret: str
    redirect_uri: Optional[str] = None


@router.get("/companies", dependencies=[Depends(_verify_admin_key)])
def list_companies(db: Session = Depends(get_db)):
    """List all companies with OAuth status and member emails."""
    companies = db.query(Company).order_by(Company.id).all()
    result = []
    for c in companies:
        oauth = db.query(Integration).filter(
            Integration.company_id == c.id, Integration.platform == "google_oauth"
        ).first()
        members = (
            db.query(User.email, CompanyMember.role)
            .join(CompanyMember, CompanyMember.user_id == User.id)
            .filter(CompanyMember.company_id == c.id, CompanyMember.is_active == True)
            .all()
        )
        result.append({
            "id": c.id, "name": c.name, "slug": c.slug, "domain": c.domain,
            "is_active": c.is_active,
            "oauth_configured": oauth is not None and oauth.config_encrypted is not None,
            "members": [{"email": email, "role": role} for email, role in members],
            "created_at": str(c.created_at) if c.created_at else None,
        })
    return {"status": "success", "data": result} # AI_RECOMMENDATION : it does N query for N companies : it might get slow, if it case there are 10K companies? how to handle it


@router.post("/companies", dependencies=[Depends(_verify_admin_key)])
def create_company(body: CompanyCreateRequest, db: Session = Depends(get_db)):
    """Create a new company/tenant with domain mapping."""
    # Check domain uniqueness
    existing = db.query(Company).filter(Company.domain == body.domain.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Domain '{body.domain}' already registered to '{existing.name}'")

    # Create company (no owner user — admin-managed)
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:100]
    counter = 1
    base_slug = slug
    while db.query(Company).filter(Company.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    company = Company(name=body.name, slug=slug, domain=body.domain.lower())
    db.add(company)
    db.commit()
    db.refresh(company)

    # Create MySQL views
    try:
        create_company_views(db, company.id)
    except Exception as e:
        logger.warning("Failed to create views for company %d: %s", company.id, e)

    logger.info("Company created: id=%d name='%s' domain='%s'", company.id, company.name, company.domain)
    return {
        "status": "success",
        "data": {"id": company.id, "name": company.name, "slug": company.slug, "domain": company.domain},
    }


@router.get("/companies/{company_id}", dependencies=[Depends(_verify_admin_key)])
def get_company(company_id: int, db: Session = Depends(get_db)):
    """Get company detail with member count."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    member_count = db.query(CompanyMember).filter(CompanyMember.company_id == company_id).count()
    return {
        "status": "success",
        "data": {
            "id": company.id, "name": company.name, "slug": company.slug,
            "domain": company.domain, "is_active": company.is_active,
            "gst_number": company.gst_number,
            "pan_number": company.pan_number,
            "member_count": member_count,
            "created_at": str(company.created_at),
        },
    }


class CompanyUpdateRequest(BaseModel):
    name: str = None
    domain: str = None
    gst_number: str = None
    pan_number: str = None


@router.put("/companies/{company_id}", dependencies=[Depends(_verify_admin_key)])
def update_company(company_id: int, body: CompanyUpdateRequest, db: Session = Depends(get_db)):
    """Update company details (name, domain, GST, PAN)."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if body.name is not None:
        company.name = body.name
    if body.domain is not None:
        company.domain = body.domain.lower()
    if body.gst_number is not None:
        company.gst_number = body.gst_number.strip().upper() or None
    if body.pan_number is not None:
        company.pan_number = body.pan_number.strip().upper() or None

    db.commit()
    db.refresh(company)
    return {
        "status": "success",
        "data": {
            "id": company.id, "name": company.name, "domain": company.domain,
            "gst_number": company.gst_number, "pan_number": company.pan_number,
        },
    }


@router.delete("/companies/{company_id}", dependencies=[Depends(_verify_admin_key)])
def delete_company(company_id: int, db: Session = Depends(get_db)):
    """Delete a company and all its data (views, members, integrations)."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Drop MySQL views
    try:
        drop_company_views(db, company_id)
    except Exception as e:
        logger.warning("Failed to drop views for company %d: %s", company_id, e)

    # Delete all tenant-scoped data (FK-safe order)
    for model in [InvoiceDraft, InvoiceRecord, ProcessedEmail, VendorCache,
                  AuditLog, Rule, VendorMapping, PlatformVendor,
                  Integration, CompanyMember]:
        db.query(model).filter(model.company_id == company_id).delete()

    # Delete company
    db.delete(company)
    db.commit()

    logger.info("Company deleted: id=%d name='%s'", company_id, company.name)
    return {"status": "success", "message": f"Company '{company.name}' deleted"}


@router.put("/companies/{company_id}/oauth", dependencies=[Depends(_verify_admin_key)])
def set_company_oauth(company_id: int, body: CompanyOAuthRequest, db: Session = Depends(get_db)):
    """Set/update Google OAuth credentials for a company."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    redirect_uri = body.redirect_uri
    if not redirect_uri:
        from app.db.system_config import sysconfig
        redirect_uri = sysconfig.get("GOOGLE_REDIRECT_URI", "")

    config = {
        "client_id": body.client_id,
        "client_secret": body.client_secret,
        "redirect_uri": redirect_uri,
    }

    # Upsert google_oauth integration for this company
    integration = db.query(Integration).filter(
        Integration.company_id == company_id, Integration.platform == "google_oauth"
    ).first()

    if integration:
        integration.config_encrypted = encrypt_config(config)
        integration.is_enabled = True
    else:
        integration = Integration(
            company_id=company_id,
            platform="google_oauth",
            display_name="Google OAuth",
            config_encrypted=encrypt_config(config),
            is_enabled=True,
        )
        db.add(integration)

    db.commit()
    logger.info("OAuth config set for company %d (%s)", company_id, company.name)
    return {"status": "success", "message": f"OAuth configured for {company.name}"}


@router.get("/companies/{company_id}/oauth", dependencies=[Depends(_verify_admin_key)])
def get_company_oauth(company_id: int, db: Session = Depends(get_db)):
    """Get OAuth config for a company (secrets masked)."""
    integration = db.query(Integration).filter(
        Integration.company_id == company_id, Integration.platform == "google_oauth"
    ).first()

    if not integration:
        return {"status": "success", "data": {"configured": False}}

    config = decrypt_config(integration.config_encrypted)
    secret = config.get("client_secret", "")
    return {
        "status": "success",
        "data": {
            "configured": True,
            "client_id": config.get("client_id", ""),
            "client_secret": (secret[:4] + "****" + secret[-4:]) if len(secret) > 8 else "****",
            "redirect_uri": config.get("redirect_uri", ""),
        },
    }


# ── Config CRUD ──────────────────────────────────────────────────────────

@router.get("/config", dependencies=[Depends(_verify_admin_key)])
def get_config():
    """Get all config values with metadata (editable, secret, has override)."""
    overrides = _load_overrides()
    base = Settings()  # fresh from .env

    config_items = []
    for key in sorted(base.model_fields.keys()):
        upper_key = key.upper()
        env_value = getattr(base, key)
        has_override = upper_key in overrides
        current_value = overrides.get(upper_key, env_value)

        config_items.append({
            "key": upper_key,
            "value": _mask_value(upper_key, current_value),
            "env_value": _mask_value(upper_key, env_value),
            "is_overridden": has_override,
            "is_editable": upper_key in EDITABLE_KEYS,
            "is_secret": upper_key in SECRET_KEYS,
            "is_readonly": upper_key in READONLY_KEYS,
        })

    return {
        "status": "success",
        "data": config_items,
        "overrides_count": len(overrides),
    }


@router.put("/config", dependencies=[Depends(_verify_admin_key)])
def update_config(body: dict = Body(...)):
    """Update one or more config values at runtime.

    Body: {"PARSER_MODE": "llm", "LLM_MODEL": "gpt-4o-mini"}
    Only keys in EDITABLE_KEYS can be changed.
    """
    overrides = _load_overrides()
    updated = []
    errors = []

    for key, value in body.items():
        upper_key = key.upper()
        if upper_key in READONLY_KEYS:
            errors.append(f"{upper_key} is read-only and cannot be changed at runtime")
            continue
        if upper_key not in EDITABLE_KEYS:
            errors.append(f"{upper_key} is not an editable config key")
            continue

        overrides[upper_key] = value
        updated.append(upper_key)
        logger.info("Admin config updated: %s = %s", upper_key,
                     _mask_value(upper_key, value))

    if updated:
        _save_overrides(overrides)

    return {
        "status": "success",
        "data": {
            "updated": updated,
            "errors": errors,
        },
    }


@router.delete("/config/{key}", dependencies=[Depends(_verify_admin_key)])
def reset_config(key: str):
    """Remove a runtime override, reverting to .env value."""
    upper_key = key.upper()
    overrides = _load_overrides()

    if upper_key not in overrides:
        return {"status": "success", "message": f"{upper_key} has no override"}

    del overrides[upper_key]
    _save_overrides(overrides)
    logger.info("Admin config reset: %s (reverted to .env)", upper_key)

    return {"status": "success", "message": f"{upper_key} reverted to .env value"}


@router.delete("/config", dependencies=[Depends(_verify_admin_key)])
def reset_all_config():
    """Remove all runtime overrides, reverting everything to .env values."""
    overrides = _load_overrides()
    count = len(overrides)
    _save_overrides({})
    logger.info("Admin config: all %d overrides cleared", count)
    return {"status": "success", "message": f"Cleared {count} overrides"}


# ── Flush ─────────────────────────────────────────────────────────────────

@router.post("/flush", dependencies=[Depends(_verify_admin_key)])
def flush_all(db: Session = Depends(get_db)):
    """Delete all invoice data, attachments, and audit logs."""
    results = {}

    attachment_dir = settings.ATTACHMENT_DIR
    if os.path.exists(attachment_dir):
        file_count = sum(1 for _, _, files in os.walk(attachment_dir) for _ in files)
        shutil.rmtree(attachment_dir)
        os.makedirs(attachment_dir, exist_ok=True)
        results["attachments_deleted"] = file_count
    else:
        results["attachments_deleted"] = 0

    for table in FLUSH_TABLES:
        try:
            row_count = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            db.execute(text(f"DELETE FROM {table}"))
            results[table] = row_count
        except Exception as e:
            results[table] = f"error: {e}"

    db.commit()

    total_rows = sum(v for v in results.values() if isinstance(v, int))
    logger.warning("FLUSH ALL executed: %s rows deleted, %s attachments removed",
                   total_rows, results.get("attachments_deleted", 0))

    return {
        "status": "success",
        "message": f"Flushed {total_rows} rows and {results['attachments_deleted']} attachment files",
        "data": results,
    }
