from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.db.repository import DraftRepository, RuleRepository
from app.db.session import get_db
from app.models.db_models import User
from app.services.draft_service import DraftService

logger = logging.getLogger(__name__)
router = APIRouter()


VALID_STATUSES = {"PENDING_REVIEW", "PENDING_VENDOR", "APPROVED", "PUSHED", "PUSH_FAILED", "REJECTED"}
VALID_PLATFORMS = {"zoho", "tally", "quickbooks"}
VALID_SOURCES = {"gmail", "stripe", "chargebee", "manual_upload"}


@router.get("")
def list_drafts(
    status: str = Query(None, description="Filter by status", enum=list(VALID_STATUSES)),
    push_to: str = Query(None, description="Filter by platform", enum=list(VALID_PLATFORMS)),
    source: str = Query(None, description="Filter by source", enum=list(VALID_SOURCES)),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List invoice drafts with optional filters."""
    repo = DraftRepository(db)
    drafts = repo.list_all(status=status, push_to=push_to, source=source, limit=limit, offset=offset) # AI_TECH_EXPLAIN : it has ui pagination support right? verify with frontend code
    total = repo.count(status=status, push_to=push_to, source=source)

    return {
        "status": "success",
        "data": [_draft_to_dict(d) for d in drafts],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/export")
def export_drafts(
    status: str = Query(None),
    push_to: str = Query(None),
    source: str = Query(None),
    db: Session = Depends(get_db),
):
    """Export drafts as Excel file."""
    service = DraftService(db)
    output = service.export_to_excel(status=status, push_to=push_to, source=source)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=invoice_drafts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"},
    )


@router.get("/{draft_id}")
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    """Get a single draft by ID."""
    repo = DraftRepository(db)
    draft = repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.put("/{draft_id}")
def update_draft(draft_id: int, body: dict, db: Session = Depends(get_db)):
    """Update draft fields (vendor_name, amount, push_to, etc.)."""
    repo = DraftRepository(db)
    allowed_fields = {
        "vendor_name", "resolved_vendor_name", "invoice_number",
        "invoice_date", "due_date", "total_amount", "tax_amount",
        "currency", "push_to",
    }
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    draft = repo.update(draft_id, **updates)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.post("/{draft_id}/approve")
def approve_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Approve a draft for pushing."""
    service = DraftService(db)
    draft = service.approve_draft(draft_id, user_id=user.id if user else None)
    if not draft:
        raise HTTPException(status_code=400, detail="Draft not found or not in PENDING_REVIEW status")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.post("/{draft_id}/reject")
def reject_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Reject a draft."""
    service = DraftService(db)
    draft = service.reject_draft(draft_id, user_id=user.id if user else None)
    if not draft:
        raise HTTPException(status_code=400, detail="Draft not found or not in valid status")
    return {"status": "success", "data": _draft_to_dict(draft)}


@router.post("/{draft_id}/push")
def push_draft(draft_id: int, db: Session = Depends(get_db)):
    """Push an approved draft to the designated billing platform.

    Credentials are loaded from the integrations table (configured via UI).
    """
    repo = DraftRepository(db)
    draft = repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status not in ("APPROVED", "PUSH_FAILED"):
        raise HTTPException(status_code=400, detail="Draft must be APPROVED or PUSH_FAILED before pushing")
    if not draft.push_to:
        raise HTTPException(status_code=400, detail="No target platform set (push_to is empty)")

    # Block push if no vendor mapping exists
    from app.db.repository import VendorMappingRepository
    mapping_repo = VendorMappingRepository(db)
    vendor_mapping = mapping_repo.get_by_alias(draft.vendor_name or "", platform=draft.push_to)
    if not vendor_mapping:
        repo.update(draft_id, status="PENDING_VENDOR", push_error=f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}")
        raise HTTPException(
            status_code=400,
            detail=f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}. Map the vendor first.",
        )

    # Update resolved vendor name from mapping before pushing
    if vendor_mapping.canonical_name:
        repo.update(draft_id, resolved_vendor_name=vendor_mapping.canonical_name)

    try:
        logger.info("Pushing draft %d to %s (vendor: %s)", draft_id, draft.push_to, vendor_mapping.canonical_name)
        result = _push_draft_to_platform(draft, db)
        repo.update(
            draft_id,
            status="PUSHED",
            external_bill_id=result.get("external_id", ""),
            push_error=None,
            pushed_at=datetime.utcnow(),
        )
        return {
            "status": "success",
            "data": {"draft_id": draft_id, "external_bill_id": result.get("external_id"), "platform": draft.push_to},
        }
    except Exception as e:
        logger.error("Push failed for draft %d: %s", draft_id, e)
        repo.update(draft_id, status="PUSH_FAILED", push_error=str(e))
        raise HTTPException(status_code=500, detail="Push failed. Check the draft's error field for details.")


@router.post("/bulk-approve")
def bulk_approve_drafts(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Bulk approve multiple drafts."""
    draft_ids = body.get("draft_ids", [])
    if len(draft_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 drafts per bulk operation")
    service = DraftService(db)
    results = service.bulk_approve(draft_ids, user_id=user.id if user else None)
    return {"status": "success", "data": results}


@router.post("/bulk-push")
def bulk_push_drafts(body: dict, db: Session = Depends(get_db)):
    """Bulk push multiple approved drafts."""
    from app.db.repository import VendorMappingRepository

    draft_ids = body.get("draft_ids", [])
    if len(draft_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 drafts per bulk operation")
    repo = DraftRepository(db)
    mapping_repo = VendorMappingRepository(db)
    results = []
    for draft_id in draft_ids:
        try:
            draft = repo.get_by_id(draft_id)
            if not draft or draft.status not in ("APPROVED", "PUSH_FAILED"):
                results.append({"draft_id": draft_id, "success": False, "error": "Not approved or failed"})
                continue
            if not draft.push_to:
                results.append({"draft_id": draft_id, "success": False, "error": "No platform set"})
                continue

            # Check vendor mapping
            vendor_mapping = mapping_repo.get_by_alias(draft.vendor_name or "", platform=draft.push_to)
            if not vendor_mapping:
                repo.update(draft_id, status="PENDING_VENDOR",
                            push_error=f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}")
                results.append({"draft_id": draft_id, "success": False,
                                "error": f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}"})
                continue

            # Update resolved name
            if vendor_mapping.canonical_name:
                repo.update(draft_id, resolved_vendor_name=vendor_mapping.canonical_name)

            result = _push_draft_to_platform(draft, db)
            repo.update(draft_id, status="PUSHED", external_bill_id=result.get("external_id", ""), push_error=None, pushed_at=datetime.utcnow())
            results.append({"draft_id": draft_id, "success": True, "external_bill_id": result.get("external_id")})
        except Exception as e:
            repo.update(draft_id, status="PUSH_FAILED", push_error=str(e))
            results.append({"draft_id": draft_id, "success": False, "error": str(e)})
    return {"status": "success", "data": results}


@router.post("/resolve-vendors")
def resolve_pending_vendors(db: Session = Depends(get_db)):
    """Check all PENDING_VENDOR drafts and auto-approve those with mappings now."""
    service = DraftService(db)
    results = service.resolve_pending_vendors()
    return {
        "status": "success",
        "data": {
            "resolved": len(results),
            "results": results,
        },
    }


@router.post("/apply-rules")
def apply_rules_to_drafts(body: dict = None, db: Session = Depends(get_db)):
    """Apply rules to drafts that don't have a push_to set yet.

    If draft_ids is provided, only apply to those drafts. Otherwise apply to all
    PENDING_REVIEW drafts without a push_to.
    """
    from app.rules.engine import apply_rules

    repo = DraftRepository(db)
    rule_repo = RuleRepository(db)

    active_rules = rule_repo.list_all(active_only=True)
    if not active_rules:
        return {"status": "success", "data": {"matched": 0, "skipped": 0, "message": "No active rules"}}

    rule_dicts = [
        {
            "id": r.id,
            "name": r.name,
            "conditions_json": r.conditions_json,
            "action_type": r.action_type,
            "action_value": r.action_value,
        }
        for r in active_rules
    ]

    # Get target drafts
    draft_ids = (body or {}).get("draft_ids")
    if draft_ids:
        drafts = [repo.get_by_id(did) for did in draft_ids]
        drafts = [d for d in drafts if d]
    else:
        drafts = repo.list_all(status="PENDING_REVIEW", limit=500) # AI_RECOMMENDATION : batch it and get 50 per batch

    matched = 0
    skipped = 0
    results = []

    for draft in drafts:
        if draft.push_to and not draft_ids:
            skipped += 1
            continue

        invoice_fields = {
            "vendor_name": draft.vendor_name or "",
            "resolved_vendor_name": draft.resolved_vendor_name or "",
            "invoice_number": draft.invoice_number or "",
            "total_amount": float(draft.total_amount) if draft.total_amount else 0,
            "tax_amount": float(draft.tax_amount) if draft.tax_amount else 0,
            "currency": draft.currency or "",
            "source": draft.source or "",
            "invoice_date": draft.invoice_date or "",
        }

        rule = apply_rules(rule_dicts, invoice_fields)
        if rule:
            repo.update(draft.id, push_to=rule["action_value"], push_to_rule_id=rule["id"])
            matched += 1
            results.append({
                "draft_id": draft.id,
                "vendor": draft.vendor_name,
                "rule_name": rule["name"],
                "push_to": rule["action_value"],
            })
        else:
            skipped += 1

    return {
        "status": "success",
        "data": {
            "matched": matched,
            "skipped": skipped,
            "results": results,
        },
    }


def _push_draft_to_platform(draft, db: Session) -> dict:
    """Push a draft to its designated billing platform using DB-stored credentials.

    Uses the platform registry - supports Zoho, Tally, QuickBooks out of the box.
    """
    from app.platforms.base import get_billing_platform

    platform = get_billing_platform(db, draft.push_to)
    return platform.push_bill(draft, db)


def _draft_to_dict(draft) -> dict:
    return {
        "id": draft.id,
        "invoice_id": draft.invoice_id,
        "vendor_name": draft.vendor_name,
        "resolved_vendor_name": draft.resolved_vendor_name,
        "invoice_number": draft.invoice_number,
        "invoice_date": draft.invoice_date,
        "due_date": draft.due_date,
        "total_amount": float(draft.total_amount) if draft.total_amount else None,
        "tax_amount": float(draft.tax_amount) if draft.tax_amount else None,
        "currency": draft.currency,
        "line_items": json.loads(draft.line_items_json) if draft.line_items_json else [],
        "source": draft.source,
        "push_to": draft.push_to,
        "push_to_rule_id": draft.push_to_rule_id,
        "status": draft.status,
        "reviewed_by": draft.reviewed_by,
        "reviewed_at": str(draft.reviewed_at) if draft.reviewed_at else None,
        "push_error": draft.push_error,
        "pushed_at": str(draft.pushed_at) if draft.pushed_at else None,
        "external_bill_id": draft.external_bill_id,
        "validation_warnings": json.loads(draft.validation_warnings) if draft.validation_warnings else [],
        "tax_breakup": json.loads(draft.tax_breakup_json) if draft.tax_breakup_json else None,
        "invoice_type": draft.invoice_type,
        "account_id": draft.account_id,
        "account_name": draft.account.name if draft.account else None,
        "created_at": str(draft.created_at) if draft.created_at else None,
        "updated_at": str(draft.updated_at) if draft.updated_at else None,
    }
