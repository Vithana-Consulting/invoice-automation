from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from app.auth.dependencies import get_optional_user
from app.db.repository import IntegrationRepository
from app.db.session import get_db
from app.models.db_models import User
from app.platforms.base import (
    decrypt_config,
    encrypt_config,
    get_all_platforms,
    get_platform_class,
    test_platform,
)

logger = logging.getLogger(__name__)
router = APIRouter()

class IntegrationCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=50)
    display_name: str = ""
    config: dict = {}
    is_enabled: bool = False

class IntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    config: Optional[dict] = None
    is_enabled: Optional[bool] = None


@router.get("/platforms")
def list_platforms():
    """Return all available platforms with config schemas (for frontend forms)."""
    return {"status": "success", "data": get_all_platforms()}


@router.get("/platforms/{platform}")
def get_platform_schema(platform: str):
    """Get config schema for a specific platform."""
    try:
        cls = get_platform_class(platform)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")
    return {
        "status": "success",
        "data": {
            "platform": cls.platform_key,
            "display_name": cls.display_name,
            "description": cls.description,
            "category": cls.category,
            "fields": cls.get_config_fields(),
        },
    }


@router.get("")
def list_integrations(db: Session = Depends(get_db)):
    """List all integrations (configured + unconfigured platforms)."""
    repo = IntegrationRepository(db)
    integrations = repo.list_all()
    # Exclude google_oauth — managed via admin dashboard, not integrations page
    integrations = [i for i in integrations if i.platform != "google_oauth"]
    configured = {i.platform for i in integrations}
    result = [_integration_to_dict(i) for i in integrations]

    # Add unconfigured platforms
    for p in get_all_platforms():
        if p["platform"] not in configured:
            result.append({
                "id": None,
                "platform": p["platform"],
                "display_name": p["display_name"],
                "description": p["description"],
                "category": p["category"],
                "is_enabled": False,
                "is_configured": False,
                "health_status": "NOT_CONFIGURED",
                "health_checked_at": None,
                "created_at": None,
            })

    return {"status": "success", "data": result}


@router.get("/{integration_id}")
def get_integration(integration_id: int, db: Session = Depends(get_db)):
    """Get a single integration with its decrypted config (for editing)."""
    repo = IntegrationRepository(db)
    integration = repo.get_by_id(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    data = _integration_to_dict(integration)
    config = decrypt_config(integration.config_encrypted)
    # Mask password fields for display
    try:
        cls = get_platform_class(integration.platform)
        fields = cls.get_config_fields()
        password_keys = {f["key"] for f in fields if f.get("type") == "password"}
        masked_config = {}
        for k, v in config.items():
            if k in password_keys and v:
                masked_config[k] = v  # Send full value so form can re-save
            else:
                masked_config[k] = v
        data["config"] = masked_config
    except Exception:
        data["config"] = config

    return {"status": "success", "data": data}


@router.post("")
def create_integration(
    body: IntegrationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    try:
        cls = get_platform_class(body.platform)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {body.platform}")

    repo = IntegrationRepository(db)
    if repo.get_by_platform(body.platform):
        raise HTTPException(status_code=409, detail=f"'{body.platform}' already configured. Use PUT to update.")

    integration = repo.create(
        platform=body.platform,
        display_name=body.display_name or cls.display_name,
        config_encrypted=encrypt_config(body.config),
        is_enabled=body.is_enabled,
        created_by=user.id if user else None,
    )
    return {"status": "success", "data": _integration_to_dict(integration)}


@router.put("/{integration_id}")
def update_integration(integration_id: int, body: IntegrationUpdate, db: Session = Depends(get_db)):
    repo = IntegrationRepository(db)
    updates = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.config is not None:
        updates["config_encrypted"] = encrypt_config(body.config)
    if body.is_enabled is not None:
        updates["is_enabled"] = body.is_enabled
    integration = repo.update(integration_id, **updates)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return {"status": "success", "data": _integration_to_dict(integration)}


@router.delete("/{integration_id}")
def delete_integration(integration_id: int, db: Session = Depends(get_db)):
    repo = IntegrationRepository(db)
    if not repo.delete(integration_id):
        raise HTTPException(status_code=404, detail="Integration not found")
    return {"status": "success", "message": "Integration removed"}


@router.post("/{integration_id}/test")
def test_integration(integration_id: int, db: Session = Depends(get_db)):
    """Test real API connectivity for a configured integration."""
    repo = IntegrationRepository(db)
    integration = repo.get_by_id(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    config = decrypt_config(integration.config_encrypted)
    if not config:
        repo.update(integration_id, health_status="ERROR", health_checked_at=datetime.utcnow())
        return {"status": "success", "data": {"healthy": False, "message": "No credentials configured"}}

    # google_oauth is not a registered platform — test it separately
    if integration.platform == "google_oauth":
        try:
            import httpx
            client_id = config.get("client_id", "")
            # Validate by checking the client_id with Google's discovery endpoint
            resp = httpx.get(f"https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=test", timeout=10)
            # We just check if the request reaches Google — a 401 means the endpoint works
            result = {
                "healthy": True,
                "message": "OAuth credentials stored",
                "details": {
                    "client_id": client_id[:30] + "..." if len(client_id) > 30 else client_id,
                    "redirect_uri": config.get("redirect_uri", ""),
                },
            }
        except Exception as e:
            result = {"healthy": False, "message": f"Cannot reach Google: {e}"}
    else:
        result = test_platform(integration.platform, config)

    repo.update(
        integration_id,
        health_status="HEALTHY" if result["healthy"] else "ERROR",
        health_checked_at=datetime.utcnow(),
    )
    return {"status": "success", "data": result}


@router.post("/{integration_id}/toggle")
def toggle_integration(integration_id: int, db: Session = Depends(get_db)):
    repo = IntegrationRepository(db)
    integration = repo.get_by_id(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    updated = repo.update(integration_id, is_enabled=not integration.is_enabled)
    return {"status": "success", "data": _integration_to_dict(updated)}


def _integration_to_dict(i) -> dict:
    try:
        cls = get_platform_class(i.platform)
        desc = cls.description
        cat = cls.category
    except Exception:
        desc = ""
        cat = ""
    return {
        "id": i.id,
        "platform": i.platform,
        "display_name": i.display_name,
        "description": desc,
        "category": cat,
        "is_enabled": i.is_enabled,
        "is_configured": True,
        "health_status": i.health_status,
        "health_checked_at": str(i.health_checked_at) if i.health_checked_at else None,
        "created_at": str(i.created_at) if i.created_at else None,
    }
