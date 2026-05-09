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

from app.db.repository import ChartOfAccountRepository, PlatformTdsTaxRepository

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
    # TDS — bill-level. Resolved from draft.account → COA(tds_section, tds_rate)
    # → platform_tds_taxes.platform_tax_id. Zoho computes the withhold amount
    # itself when tds_tax_id is set on the bill.
    tds_tax_id: Optional[str] = None
    tds_section: Optional[str] = None
    tds_rate: Optional[float] = None
    # Per-line-item: hsn_code → platform_account_id
    hsn_account_map: dict = None

    def __post_init__(self):
        if self.hsn_account_map is None:
            self.hsn_account_map = {}

    @property
    def has_tax_lines(self) -> bool:
        return any([self.cgst_amount, self.sgst_amount, self.igst_amount])


def resolve_accounts_for_platform(draft, platform: str, db: Session) -> ResolvedAccounts:
    """Look up the correct platform account IDs for a draft.

    Resolution priority per line item:
      1. HSN/SAC code match in Chart of Accounts (hsn_codes field)
      2. Draft's assigned account (account_id → platform_account_id)
      3. Default PURCHASE account for this platform (is_default + sub_type=PURCHASE)
    """
    result = ResolvedAccounts()
    coa_repo = ChartOfAccountRepository(db)

    # 1. Build per-HSN account map from invoice line items
    invoice = getattr(draft, "invoice", None)
    if invoice and invoice.line_items_json:
        try:
            line_items = json.loads(invoice.line_items_json)
            logger.info("[COA] Invoice %s has %d line items", getattr(invoice, "id", "?"), len(line_items))
            for item in line_items:
                hsn = (item.get("hsn_or_sac") or item.get("hsn_sac_code") or item.get("hsn_code") or "").strip()
                logger.info("[COA] Line item '%s' HSN='%s'", item.get("description", "")[:40], hsn)
                if hsn and hsn not in result.hsn_account_map:
                    coa = coa_repo.get_by_hsn(hsn, platform)
                    if coa:
                        result.hsn_account_map[hsn] = coa.platform_account_id
                        logger.info("[COA] HSN '%s' → '%s' (%s)", hsn, coa.name, coa.platform_account_id)
                    else:
                        logger.info("[COA] HSN '%s' → no match on platform=%s", hsn, platform)
                elif not hsn:
                    logger.info("[COA] Line item has no HSN code")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("[COA] Failed to parse line_items_json: %s", e)
    else:
        logger.info("[COA] No line_items_json on invoice")

    # 2. Resolve draft-level main account (expense/income)
    if draft.account_id and draft.account:
        if draft.account.platform == platform:
            result.main_account_ref = draft.account.platform_account_id
        else:
            sub = draft.account.sub_type or "PURCHASE"
            fallback = coa_repo.get_default(sub, platform)
            if fallback:
                result.main_account_ref = fallback.platform_account_id

    # 3. Fall back to default PURCHASE account for this platform
    if not result.main_account_ref:
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

    # 4. TDS — pulled from the draft's account (COA). Section + rate drive
    # the lookup against synced platform_tds_taxes; an explicit override on
    # the COA (tds_tax_id) wins. Silently skipped if any link is missing.
    coa = getattr(draft, "account", None)
    if coa and coa.platform == platform and (coa.tds_section or coa.tds_rate is not None or coa.tds_tax_id):
        result.tds_section = coa.tds_section
        try:
            result.tds_rate = float(coa.tds_rate) if coa.tds_rate is not None else None
        except (TypeError, ValueError):
            result.tds_rate = None

        if coa.tds_tax_id:
            result.tds_tax_id = coa.tds_tax_id
        elif coa.tds_section and result.tds_rate is not None:
            tds_repo = PlatformTdsTaxRepository(db)
            match = tds_repo.find_by_section_rate(platform, coa.tds_section, coa.tds_rate)
            if match:
                result.tds_tax_id = match.platform_tax_id
                logger.info(
                    "[TDS] Resolved %s @ %s%% → tax_id=%s (account=%s)",
                    coa.tds_section, result.tds_rate, match.platform_tax_id, coa.name,
                )
            else:
                logger.warning(
                    "[TDS] No platform_tds_taxes match for %s @ %s%% on platform=%s. "
                    "Run 'Sync TDS' on Chart of Accounts page.",
                    coa.tds_section, result.tds_rate, platform,
                )

    return result
