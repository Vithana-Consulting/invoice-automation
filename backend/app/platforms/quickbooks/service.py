from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.platforms.base import BillingPlatform, register_billing
from app.platforms.quickbooks.client import QuickBooksAuth, QuickBooksClient

logger = logging.getLogger(__name__)


@register_billing
class QuickBooksBilling(BillingPlatform):
    platform_key = "quickbooks"
    display_name = "QuickBooks Online"
    description = "Push bills to QuickBooks Online"
    category = "billing"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        auth = QuickBooksAuth(
            client_id=config.get("client_id", ""),
            client_secret=config.get("client_secret", ""),
            refresh_token=config.get("refresh_token", ""),
        )
        self.client = QuickBooksClient(
            auth=auth,
            realm_id=config.get("realm_id", ""),
            base_url=config.get("base_url", "https://quickbooks.api.intuit.com"),
        )

    def test_connection(self) -> Dict[str, Any]:
        try:
            info = self.client.get_company_info()
            name = info.get("CompanyInfo", {}).get("CompanyName", "?")
            return {"healthy": True, "message": f"Connected to QuickBooks ({name})"}
        except Exception as e:
            return {"healthy": False, "message": str(e)}

    def push_bill(self, draft: Any, db: Session) -> Dict[str, Any]:
        from app.db.repository import VendorMappingRepository

        vendor_name = draft.resolved_vendor_name or draft.vendor_name or "Unknown Vendor"

        # Check vendor mapping first
        mapping_repo = VendorMappingRepository(db)
        mapping = mapping_repo.get_by_alias(draft.vendor_name or "", platform="quickbooks")

        vendor_ref = None
        if mapping and mapping.platform_vendor_id:
            vendor_ref = mapping.platform_vendor_id
            vendor_name = mapping.canonical_name
        else:
            vendor_ref = self.find_vendor(vendor_name)

        if not vendor_ref:
            raise Exception(
                f"Vendor '{vendor_name}' not found on QuickBooks and no vendor mapping exists. "
                "Create a vendor mapping in Vendor Mappings before pushing."
            )

        # Resolve COA → QuickBooks account IDs
        from app.platforms.account_resolver import resolve_accounts_for_platform
        accounts = resolve_accounts_for_platform(draft, "quickbooks", db)

        main_account_ref = accounts.main_account_ref or "1"  # fallback to QB default
        amount = float(draft.total_amount) if draft.total_amount else 0.0

        # Subtract tax from main line if we're creating separate tax lines
        main_amount = amount
        if accounts.has_tax_lines:
            main_amount = amount - accounts.cgst_amount - accounts.sgst_amount - accounts.igst_amount

        lines = [{
            "Amount": round(main_amount, 2),
            "DetailType": "AccountBasedExpenseLineDetail",
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": main_account_ref},
            },
            "Description": f"Invoice {draft.invoice_number or draft.id}",
        }]

        # Add separate tax lines
        if accounts.cgst_amount and accounts.cgst_account_ref:
            lines.append({
                "Amount": round(accounts.cgst_amount, 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": accounts.cgst_account_ref}},
                "Description": "CGST",
            })
        if accounts.sgst_amount and accounts.sgst_account_ref:
            lines.append({
                "Amount": round(accounts.sgst_amount, 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": accounts.sgst_account_ref}},
                "Description": "SGST",
            })
        if accounts.igst_amount and accounts.igst_account_ref:
            lines.append({
                "Amount": round(accounts.igst_amount, 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": accounts.igst_account_ref}},
                "Description": "IGST",
            })

        payload = {
            "VendorRef": {"value": vendor_ref},
            "Line": lines,
            "DocNumber": draft.invoice_number or f"BILL-{draft.id}",
        }

        # Set currency from invoice
        currency = draft.currency or "INR"
        if currency != "USD":
            payload["CurrencyRef"] = {"value": currency}

        if draft.invoice_date:
            payload["TxnDate"] = draft.invoice_date
        if draft.due_date:
            payload["DueDate"] = draft.due_date

        result = self.client.create_bill(payload)
        bill = result.get("Bill", {})
        return {"external_id": str(bill.get("Id", "")), "platform": "quickbooks"}

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Fetch Chart of Accounts from QuickBooks Online."""
        try:
            result = self.client.query("SELECT * FROM Account MAXRESULTS 500")
            accounts = result.get("QueryResponse", {}).get("Account", [])
            return [
                {
                    "id": str(a.get("Id", "")),
                    "name": a.get("Name", ""),
                    "code": a.get("AcctNum", ""),
                    "type": a.get("AccountType", ""),
                    "description": a.get("Description", ""),
                    "is_active": a.get("Active", True),
                    "parent_id": str(a.get("ParentRef", {}).get("value", "")) if a.get("ParentRef") else None,
                    "platform": "quickbooks",
                }
                for a in accounts
            ]
        except Exception as e:
            logger.error("Failed to list QuickBooks accounts: %s", e)
            return []

    def list_vendors(self) -> List[Dict[str, Any]]:
        try:
            result = self.client.query("SELECT * FROM Vendor MAXRESULTS 500")
            vendors = result.get("QueryResponse", {}).get("Vendor", [])
            return [
                {
                    "id": str(v.get("Id", "")),
                    "name": v.get("DisplayName", ""),
                    "email": v.get("PrimaryEmailAddr", {}).get("Address", "") if v.get("PrimaryEmailAddr") else "",
                    "status": "active" if v.get("Active", True) else "inactive",
                    "platform": "quickbooks",
                }
                for v in vendors
            ]
        except Exception as e:
            logger.error("Failed to list QuickBooks vendors: %s", e)
            return []

    def find_vendor(self, vendor_name: str) -> Optional[str]:
        try:
            vendors = self.client.find_vendor(vendor_name)
            if vendors:
                return str(vendors[0]["Id"])
        except Exception as e:
            logger.warning("QB vendor search failed: %s", e)
        return None

    def create_vendor(self, vendor_name: str, **kwargs) -> str:
        result = self.client.create_vendor(vendor_name)
        return str(result.get("Vendor", {}).get("Id", ""))

    @classmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        return [
            {"key": "client_id", "label": "Client ID", "type": "text", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password", "required": True},
            {"key": "refresh_token", "label": "Refresh Token", "type": "password", "required": True},
            {"key": "realm_id", "label": "Realm ID (Company ID)", "type": "text", "required": True},
            {"key": "base_url", "label": "API Base URL", "type": "text", "required": True,
             "default": "https://sandbox-quickbooks.api.intuit.com"},
        ]
