from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.platforms.base import BillingPlatform, register_billing
from app.platforms.zoho.auth import ZohoAuth
from app.platforms.zoho.client import ZohoClient
from app.platforms.zoho.mappers import build_vendor_payload, invoice_to_zoho_bill

logger = logging.getLogger(__name__)


@register_billing
class ZohoBilling(BillingPlatform):
    platform_key = "zoho"
    display_name = "Zoho Books"
    description = "Push bills to Zoho Books"
    category = "billing"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.auth = ZohoAuth(
            client_id=config.get("client_id", ""),
            client_secret=config.get("client_secret", ""),
            refresh_token=config.get("refresh_token", ""),
            auth_url=config.get("auth_url", "https://accounts.zoho.in/oauth/v2/token"),
        )
        self.client = ZohoClient(
            auth=self.auth,
            base_url=config.get("base_url", "https://www.zohoapis.in/books/v3"),
            organization_id=config.get("organization_id", ""),
            default_account_id=config.get("default_account_id", ""),
        )

    def test_connection(self) -> Dict[str, Any]:
        try:
            token = self.auth.get_access_token()
            # Try fetching org info to verify full connectivity
            details = {
                "organization_id": self.config.get("organization_id", ""),
                "base_url": self.config.get("base_url", ""),
                "auth_url": self.config.get("auth_url", ""),
            }
            try:
                import httpx
                resp = httpx.get(
                    f"{self.client.base_url}/organizations",
                    headers={"Authorization": f"Zoho-oauthtoken {token}"},
                    timeout=15,
                )
                org_list = resp.json().get("organizations", [])
                if org_list:
                    org = org_list[0]
                    details["org_name"] = org.get("name", "")
                    details["plan"] = org.get("plan_type", "")
                    details["currency"] = org.get("currency_code", "")
            except Exception:
                pass  # Token works, org fetch is bonus info
            return {"healthy": True, "message": f"Connected to Zoho Books", "details": details}
        except Exception as e:
            return {
                "healthy": False,
                "message": str(e),
                "details": {
                    "auth_url": self.config.get("auth_url", ""),
                    "hint": "Check that client_id, client_secret, and refresh_token are correct and not expired.",
                },
            }

    def push_bill(self, draft: Any, db: Session) -> Dict[str, Any]:
        # AI_RECOMMENDATION , AI_RESEARCH , AI_USER_VALIDATION_BEFORE_IMPLEMENTATION : ALL THE WORKFLOW FOR NOW, WORKS FOR INVOICES MEANING bills in zoho not sales. so the i/(s & c)gst. has to be pushed to the inbound gsts (look at how a single bill with i/(s&c)gsts included in the amount gets created as a new bill inbound expense coa, for more context refer the zoho's working and auditors' mindset on this)
        from app.db.repository import VendorMappingRepository

        invoice = draft.invoice
        vendor_name = draft.resolved_vendor_name or draft.vendor_name or "Unknown Vendor"

        # Check vendor mapping first — use platform_vendor_id if available
        mapping_repo = VendorMappingRepository(db)
        mapping = mapping_repo.get_by_alias(draft.vendor_name or "", platform="zoho")

        vendor_id = None
        if mapping and mapping.platform_vendor_id:
            # Use the mapped vendor ID directly
            vendor_id = mapping.platform_vendor_id
            vendor_name = mapping.canonical_name
        else:
            # Search Zoho for the resolved vendor name
            vendor_id = self.find_vendor(vendor_name)

        if not vendor_id:
            raise Exception(
                f"Vendor '{vendor_name}' not found on Zoho and no vendor mapping exists. "
                "Create a vendor mapping in Vendor Mappings before pushing."
            )

        # Resolve COA → Zoho account IDs
        from app.platforms.account_resolver import resolve_accounts_for_platform
        accounts = resolve_accounts_for_platform(draft, "zoho", db)

        # Build and push (COA accounts take priority, fallback to config default)
        payload = invoice_to_zoho_bill(
            invoice, vendor_id,
            accounts=accounts,
            fallback_account_id=self.client.default_account_id,
        )
        result = self.client.create_bill(payload)
        bill = result.get("bill", {})
        return {"external_id": bill.get("bill_id", ""), "platform": "zoho"}

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Fetch Chart of Accounts from Zoho Books."""
        try:
            accounts = self.client.list_chartofaccounts()
            results = []
            for a in accounts:
                results.append({
                    "id": str(a.get("account_id", "")),
                    "name": a.get("account_name", ""),
                    "code": a.get("account_code", ""),
                    "type": a.get("account_type", ""),
                    "description": a.get("description", ""),
                    "is_active": a.get("is_active", True),
                    "parent_id": str(a.get("parent_account_id", "")) if a.get("parent_account_id") else None,
                    "platform": "zoho",
                    "raw": a,
                })
            return results
        except Exception as e:
            logger.error("Failed to list Zoho accounts: %s", e)
            return []

    def list_vendors(self) -> List[Dict[str, Any]]:
        try:
            contacts = self.client.list_contacts()
            return [
                {
                    "id": c.get("contact_id", ""),
                    "name": c.get("contact_name", ""),
                    "email": c.get("email", ""),
                    "status": c.get("status", ""),
                    "platform": "zoho",
                }
                for c in contacts
            ]
        except Exception as e:
            logger.error("Failed to list Zoho vendors: %s", e)
            return []

    def find_vendor(self, vendor_name: str) -> Optional[str]:
        try:
            contacts = self.client.list_contacts(contact_name=vendor_name)
            for c in contacts:
                if c.get("contact_name", "").lower() == vendor_name.lower():
                    return c["contact_id"]
        except Exception as e:
            logger.warning("Zoho vendor search failed: %s", e)
        return None

    def create_vendor(self, vendor_name: str, **kwargs) -> str:
        payload = build_vendor_payload(vendor_name, kwargs.get("gst_number"))
        # AI_RECOMMENDATION : while creating an vendor, mandatory fields are name, address, gst, pan
        result = self.client.create_contact(payload)
        return result.get("contact", {}).get("contact_id", "")

    @classmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        return [
            {"key": "client_id", "label": "Client ID", "type": "text", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password", "required": True},
            {"key": "refresh_token", "label": "Refresh Token", "type": "password", "required": True},
            {"key": "organization_id", "label": "Organization ID", "type": "text", "required": True},
            {"key": "base_url", "label": "API Base URL", "type": "text", "required": True,
             "default": "https://www.zohoapis.in/books/v3"},
            {"key": "auth_url", "label": "Auth URL", "type": "text", "required": True,
             "default": "https://accounts.zoho.in/oauth/v2/token"},
            {"key": "default_account_id", "label": "Default Account ID (Chart of Accounts)", "type": "text",
             "required": False},
        ]
