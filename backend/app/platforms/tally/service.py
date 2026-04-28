from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.platforms.base import BillingPlatform, register_billing
from app.platforms.tally.client import TallyClient

logger = logging.getLogger(__name__)


@register_billing
class TallyBilling(BillingPlatform):
    platform_key = "tally"
    display_name = "Tally Prime"
    description = "Push purchase vouchers to Tally"
    category = "billing"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client = TallyClient(
            host=config.get("host", "http://localhost:9000"),
            company_name=config.get("company_name", ""),
        )

    def test_connection(self) -> Dict[str, Any]:
        try:
            return self.client.test_connection()
        except Exception as e:
            return {"healthy": False, "message": str(e)}

    def push_bill(self, draft: Any, db: Session) -> Dict[str, Any]:
        from app.db.repository import VendorMappingRepository

        vendor_name = draft.resolved_vendor_name or draft.vendor_name or "Unknown Vendor"

        # Check vendor mapping — Tally uses ledger names, so canonical_name is the ledger
        mapping_repo = VendorMappingRepository(db)
        mapping = mapping_repo.get_by_alias(draft.vendor_name or "", platform="tally")
        if not mapping:
            raise Exception(
                f"No vendor mapping for '{draft.vendor_name}' on Tally. "
                "Create a vendor mapping in Vendor Mappings before pushing."
            )
        vendor_name = mapping.canonical_name

        bill_number = draft.invoice_number or f"BILL-{draft.id}"
        date = draft.invoice_date or ""
        amount = float(draft.total_amount) if draft.total_amount else 0.0

        # Resolve COA → Tally ledger names
        from app.platforms.account_resolver import resolve_accounts_for_platform
        accounts = resolve_accounts_for_platform(draft, "tally", db)

        xml = self.client.build_purchase_voucher_xml(
            vendor_name=vendor_name,
            bill_number=bill_number,
            date=date,
            amount=amount,
            accounts=accounts,
            narration=f"Auto-imported from invoice {draft.invoice_number}",
        )
        result = self.client.create_voucher(xml)

        if "CREATED" in result.upper() or "LINEERROR" not in result.upper():
            return {"external_id": bill_number, "platform": "tally"}
        raise Exception(f"Tally voucher creation failed: {result[:300]}")

    def find_vendor(self, vendor_name: str) -> Optional[str]:
        # Tally doesn't have a vendor search API - vendors are ledgers
        return None

    def create_vendor(self, vendor_name: str, **kwargs) -> str:
        # Tally auto-creates ledgers on voucher import
        return vendor_name

    @classmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        return [
            {"key": "host", "label": "Tally Host URL", "type": "text", "required": True,
             "default": "http://localhost:9000"},
            {"key": "company_name", "label": "Company Name", "type": "text", "required": True},
            {"key": "purchase_ledger", "label": "Purchase Ledger Name", "type": "text",
             "required": False, "default": "Purchase Accounts"},
        ]
