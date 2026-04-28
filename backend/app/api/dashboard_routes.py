from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.repository import AuditLogRepository, DraftRepository, IntegrationRepository
from app.db.session import get_db
from app.services.draft_service import DraftService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    """Get dashboard summary counts."""
    service = DraftService(db)
    summary = service.get_dashboard_summary()

    # Count by source (uses platform registry for billing, known sources for ingestion)
    draft_repo = DraftRepository(db)
    from app.platforms.base import _SOURCE_REGISTRY, _BILLING_REGISTRY
    source_keys = list(_SOURCE_REGISTRY.keys()) + ["manual_upload"]
    by_source = {s: draft_repo.count(source=s) for s in source_keys}

    # Count by push_to platform
    platform_keys = list(_BILLING_REGISTRY.keys())
    by_platform = {p: draft_repo.count(push_to=p) for p in platform_keys}
    by_platform["unassigned"] = draft_repo.count(push_to=None)

    return {
        "status": "success",
        "data": {
            **summary,
            "by_source": by_source,
            "by_platform": by_platform,
        },
    }


@router.get("/recent-activity")
def recent_activity(db: Session = Depends(get_db)):
    """Get recent audit log entries."""
    repo = AuditLogRepository(db) # AI_TECH_EXPLAIN : Y are u using mysql for audit? is it realiable/scalable/effeicent?
    entries = repo.list_recent(limit=20)
    return {
        "status": "success",
        "data": [
            {
                "id": e.id,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "action": e.action,
                "details": json.loads(e.details) if e.details else None,
                "status": e.status,
                "error": e.error_message,
                "created_at": str(e.created_at) if e.created_at else None,
            }
            for e in entries
        ],
    }


@router.get("/integration-health")
def integration_health(db: Session = Depends(get_db)):
    """Get health status of all enabled integrations."""
    repo = IntegrationRepository(db)
    integrations = repo.list_all()
    return {
        "status": "success",
        "data": [
            {
                "platform": i.platform,
                "display_name": i.display_name,
                "is_enabled": i.is_enabled,
                "health_status": i.health_status,
                "health_checked_at": str(i.health_checked_at) if i.health_checked_at else None,
            }
            for i in integrations
        ],
    }
