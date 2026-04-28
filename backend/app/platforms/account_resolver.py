"""Resolve Chart of Accounts entries to platform-specific account IDs.

Each COA entry is synced FROM a platform and has a `platform_account_id`.
This module reads the draft's assigned account + tax accounts and returns
the platform-native IDs for the push API.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.db.repository import ChartOfAccountRepository

logger = logging.getLogger(__name__)


@dataclass
class ResolvedAccounts:
    """Platform-native account IDs resolved from COA."""
    main_account_ref: Optional[str] = None
    cgst_account_ref: Optional[str] = None
    sgst_account_ref: Optional[str] = None
    igst_account_ref: Optional[str] = None
    cgst_amount: float = 0
    sgst_amount: float = 0
    igst_amount: float = 0

    @property
    def has_tax_lines(self) -> bool:
        return any([self.cgst_amount, self.sgst_amount, self.igst_amount])


def resolve_accounts_for_platform(draft, platform: str, db: Session) -> ResolvedAccounts:
    """Look up the correct platform account IDs for a draft.

    Uses the synced COA entries tagged with sub_type and is_default.
    """
    result = ResolvedAccounts()
    coa_repo = ChartOfAccountRepository(db)

    # 1. Resolve main account (expense/income)
    if draft.account_id and draft.account:
        # The assigned account already has a platform_account_id
        if draft.account.platform == platform:
            result.main_account_ref = draft.account.platform_account_id
        else:
            # Account is from a different platform — find equivalent on target platform
            sub = draft.account.sub_type or "PURCHASE"
            fallback = coa_repo.get_default(sub, platform)
            if fallback:
                result.main_account_ref = fallback.platform_account_id

    if not result.main_account_ref:
        # No account assigned — use default PURCHASE/SALE for this platform
        sub = "PURCHASE" if draft.invoice_type != "OUTBOUND" else "SALE"
        default = coa_repo.get_default(sub, platform)
        if default:
            result.main_account_ref = default.platform_account_id

    # 2. Parse tax breakup amounts
    if draft.tax_breakup_json:
        try:
            tb = json.loads(draft.tax_breakup_json)
            result.cgst_amount = float(tb.get("cgst_amount") or 0)
            result.sgst_amount = float(tb.get("sgst_amount") or 0)
            result.igst_amount = float(tb.get("igst_amount") or 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # 3. Resolve tax accounts (default COA for each tax type on this platform)
    if result.cgst_amount:
        acc = coa_repo.get_default("TAX_CGST", platform)
        if acc:
            result.cgst_account_ref = acc.platform_account_id

    if result.sgst_amount:
        acc = coa_repo.get_default("TAX_SGST", platform)
        if acc:
            result.sgst_account_ref = acc.platform_account_id

    if result.igst_amount:
        acc = coa_repo.get_default("TAX_IGST", platform)
        if acc:
            result.igst_account_ref = acc.platform_account_id

    return result
