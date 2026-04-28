"""Chart of Accounts API — synced from billing platforms, editable locally.

Flow:
  1. User connects Zoho/QB in Integrations
  2. POST /api/coa/sync/{platform} → fetches accounts from platform API
  3. Accounts stored locally, user tags them (sub_type, hsn_codes, is_default)
  4. On invoice push, system uses tagged accounts to set correct account IDs
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.repository import ChartOfAccountRepository
from app.db.session import get_db
from app.models.db_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


class COATagUpdate(BaseModel):
    """Editable fields — user tags synced accounts with these."""
    sub_type: Optional[str] = None  # PURCHASE | SALE | TAX_CGST | TAX_SGST | TAX_IGST | TAX_CESS
    hsn_codes: Optional[list[str]] = None
    is_default: Optional[bool] = None


# ─── List Accounts ───────────────────────────────────────────────────────

@router.get("")
def list_accounts(
    platform: str = Query(None, description="Filter by platform (zoho, quickbooks, tally)"),
    type: str = Query(None, description="Filter by account type"),
    sub_type: str = Query(None, description="Filter by sub_type tag"),
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = ChartOfAccountRepository(db)
    accounts = repo.list_all(platform=platform, type_filter=type, sub_type=sub_type, active_only=active_only) # AI_RECOMMENDATION : Batch fetch it, batch size 50
    return {
        "status": "success",
        "data": [_account_to_dict(a) for a in accounts],
    }


# ─── Sync from Platform ─────────────────────────────────────────────────

@router.post("/sync/{platform}")
def sync_from_platform(
    platform: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync Chart of Accounts from a billing platform (Zoho, QuickBooks, etc.).

    Fetches all accounts from the platform API and upserts locally.
    Preserves any local edits (sub_type, hsn_codes, is_default) on existing records.
    """
    from app.platforms.base import get_billing_platform

    try:
        billing = get_billing_platform(db, platform)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    accounts = billing.list_accounts()
    if not accounts:
        raise HTTPException(status_code=404, detail=f"No accounts returned from {platform}. Check the integration connection.")

    repo = ChartOfAccountRepository(db)
    result = repo.sync_from_platform(platform, accounts)

    # Auto-tag tax accounts based on name patterns (AI-like heuristic)
    _auto_tag_accounts(repo, platform)

    return {
        "status": "success",
        "message": f"Synced {result['total']} accounts from {platform} ({result['created']} new, {result['updated']} updated)",
        "data": result,
    }


# ─── Tag Account (Edit) ─────────────────────────────────────────────────

@router.put("/{account_id}")
def tag_account(
    account_id: int,
    body: COATagUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tag a synced account with sub_type, HSN codes, or mark as default."""
    repo = ChartOfAccountRepository(db)
    existing = repo.get_by_id(account_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    updates = {}
    if body.sub_type is not None:
        updates["sub_type"] = body.sub_type or None
    if body.hsn_codes is not None:
        updates["hsn_codes"] = json.dumps(body.hsn_codes) if body.hsn_codes else None
    if body.is_default is not None:
        updates["is_default"] = body.is_default

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    acc = repo.update(account_id, **updates)
    return {"status": "success", "data": _account_to_dict(acc)}


# ─── Bulk Tag (for quick setup) ──────────────────────────────────────────

@router.post("/auto-tag/{platform}")
def auto_tag(
    platform: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Auto-tag synced accounts based on name/type heuristics.

    Uses keyword matching to detect:
    - CGST/SGST/IGST tax accounts
    - Purchase/expense accounts
    - Sales/income accounts
    """
    repo = ChartOfAccountRepository(db)
    tagged = _auto_tag_accounts(repo, platform)
    return {
        "status": "success",
        "message": f"Auto-tagged {tagged} accounts on {platform}",
    }


# ─── Delete / Deactivate ────────────────────────────────────────────────

@router.delete("/{account_id}")
def deactivate_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = ChartOfAccountRepository(db)
    existing = repo.get_by_id(account_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")
    repo.update(account_id, is_active=False)
    return {"status": "success", "message": f"Account '{existing.name}' deactivated"}


# ─── Helpers ─────────────────────────────────────────────────────────────

def _auto_tag_accounts(repo: ChartOfAccountRepository, platform: str) -> int:
    """Auto-tag accounts based on name keywords. Returns count of accounts tagged."""
    accounts = repo.list_all(platform=platform, active_only=False)
    tagged = 0

    for acc in accounts:
        if acc.sub_type:  # Don't overwrite user-set tags
            continue

        name_lower = acc.name.lower()
        account_type = acc.type.lower()
        new_sub_type = None
        new_is_default = False

        # Tax account detection
        if "cgst" in name_lower and "input" in name_lower:
            new_sub_type = "TAX_CGST"
            new_is_default = True
        elif "sgst" in name_lower and "input" in name_lower:
            new_sub_type = "TAX_SGST"
            new_is_default = True
        elif "igst" in name_lower and "input" in name_lower:
            new_sub_type = "TAX_IGST"
            new_is_default = True
        elif "cgst" in name_lower and ("output" in name_lower or "liability" in name_lower or "payable" in name_lower):
            new_sub_type = "TAX_CGST"
        elif "sgst" in name_lower and ("output" in name_lower or "liability" in name_lower or "payable" in name_lower):
            new_sub_type = "TAX_SGST"
        elif "igst" in name_lower and ("output" in name_lower or "liability" in name_lower or "payable" in name_lower):
            new_sub_type = "TAX_IGST"
        elif "cess" in name_lower:
            new_sub_type = "TAX_CESS"
        # Purchase/expense detection
        elif any(kw in name_lower for kw in ["purchase", "cost of goods", "cogs", "bought"]):
            new_sub_type = "PURCHASE"
        elif account_type in ("expense", "cost_of_goods_sold"):
            new_sub_type = "PURCHASE"
        # Sales/income detection
        elif any(kw in name_lower for kw in ["sales", "revenue", "income from"]):
            new_sub_type = "SALE"
        elif account_type in ("income", "other_income"):
            new_sub_type = "SALE"

        if new_sub_type:
            updates = {"sub_type": new_sub_type}
            # Set as default only if no default exists for this sub_type on this platform
            if new_is_default and not repo.get_default(new_sub_type, platform):
                updates["is_default"] = True
            repo.update(acc.id, **updates)
            tagged += 1

    return tagged


def _account_to_dict(acc) -> dict:
    return {
        "id": acc.id,
        "platform": acc.platform,
        "platform_account_id": acc.platform_account_id,
        "code": acc.code,
        "name": acc.name,
        "type": acc.type,
        "description": acc.description,
        "parent_platform_id": acc.parent_platform_id,
        "is_active": acc.is_active,
        "sub_type": acc.sub_type,
        "hsn_codes": json.loads(acc.hsn_codes) if acc.hsn_codes else [],
        "is_default": acc.is_default,
        "synced_at": str(acc.synced_at) if acc.synced_at else None,
    }
