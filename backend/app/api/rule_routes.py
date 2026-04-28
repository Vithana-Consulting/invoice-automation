from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.db.repository import RuleRepository
from app.db.session import get_db
from app.models.db_models import User
from app.rules.engine import apply_rules, evaluate_rule
from app.rules.schema import RuleCreate, RuleEvaluateRequest, RuleReorder, RuleUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
def list_rules(db: Session = Depends(get_db)):
    """List all rules ordered by priority."""
    repo = RuleRepository(db)
    rules = repo.list_all()
    return {
        "status": "success",
        "data": [_rule_to_dict(r) for r in rules],
    }


@router.post("")
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """Create a new rule."""
    repo = RuleRepository(db)
    conditions_json = body.conditions.model_dump_json()
    rule = repo.create(
        name=body.name,
        description=body.description,
        priority=body.priority,
        is_active=body.is_active,
        conditions_json=conditions_json,
        action_type=body.action_type,
        action_value=body.action_value,
        created_by=user.id if user else None,
    )
    return {"status": "success", "data": _rule_to_dict(rule)}


@router.put("/reorder")
def reorder_rules(body: RuleReorder, db: Session = Depends(get_db)):
    """Reorder rules by priority."""
    repo = RuleRepository(db)
    repo.reorder(body.rule_ids)
    rules = repo.list_all()
    return {"status": "success", "data": [_rule_to_dict(r) for r in rules]}


@router.post("/evaluate")
def evaluate_rules(body: RuleEvaluateRequest, db: Session = Depends(get_db)):
    """Dry-run: evaluate rules against given invoice fields."""
    repo = RuleRepository(db)
    active_rules = repo.list_all(active_only=True)
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
    matched = apply_rules(rule_dicts, body.invoice_fields)
    if matched:
        return {
            "status": "success",
            "data": {
                "matched": True,
                "rule_id": matched["id"],
                "rule_name": matched["name"],
                "action_type": matched["action_type"],
                "action_value": matched["action_value"],
            },
        }
    return {"status": "success", "data": {"matched": False}}


@router.put("/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, db: Session = Depends(get_db)):
    """Update a rule."""
    repo = RuleRepository(db)
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.priority is not None:
        updates["priority"] = body.priority
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    if body.conditions is not None:
        updates["conditions_json"] = body.conditions.model_dump_json()
    if body.action_type is not None:
        updates["action_type"] = body.action_type
    if body.action_value is not None:
        updates["action_value"] = body.action_value

    rule = repo.update(rule_id, **updates)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "success", "data": _rule_to_dict(rule)}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    """Delete a rule."""
    repo = RuleRepository(db)
    if not repo.delete(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "success", "message": "Rule deleted"}


@router.post("/{rule_id}/toggle")
def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    """Toggle a rule's active status."""
    repo = RuleRepository(db)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    updated = repo.update(rule_id, is_active=not rule.is_active)
    return {"status": "success", "data": _rule_to_dict(updated)}


@router.post("/{rule_id}/apply")
def apply_single_rule(rule_id: int, db: Session = Depends(get_db)):
    """Apply a single rule to all PENDING_REVIEW drafts without push_to."""
    from app.db.repository import DraftRepository

    repo = RuleRepository(db)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    draft_repo = DraftRepository(db)
    drafts = draft_repo.list_all(status="PENDING_REVIEW", limit=500)

    conditions = rule.conditions_json
    if isinstance(conditions, str):
        conditions = json.loads(conditions)

    matched = 0
    results = []
    for draft in drafts:
        if draft.push_to:
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

        if evaluate_rule(conditions, invoice_fields):
            draft_repo.update(draft.id, push_to=rule.action_value, push_to_rule_id=rule.id)
            matched += 1
            results.append({"draft_id": draft.id, "vendor": draft.vendor_name, "push_to": rule.action_value})

    return {
        "status": "success",
        "data": {
            "rule_name": rule.name,
            "matched": matched,
            "results": results,
        },
    }


def _rule_to_dict(rule) -> dict:
    conditions = rule.conditions_json
    if isinstance(conditions, str):
        try:
            conditions = json.loads(conditions)
        except json.JSONDecodeError:
            pass
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "priority": rule.priority,
        "is_active": rule.is_active,
        "conditions": conditions,
        "action_type": rule.action_type,
        "action_value": rule.action_value,
        "created_at": str(rule.created_at) if rule.created_at else None,
        "updated_at": str(rule.updated_at) if rule.updated_at else None,
    }
