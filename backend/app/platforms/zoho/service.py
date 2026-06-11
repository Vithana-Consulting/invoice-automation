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
        org_id = config.get("organization_id", "")
        self.auth = ZohoAuth(
            client_id=config.get("client_id", ""),
            client_secret=config.get("client_secret", ""),
            refresh_token=config.get("refresh_token", ""),
            auth_url=config.get("auth_url", "https://accounts.zoho.in/oauth/v2/token"),
            # Optional list of backup credential sets for rate-limit/auth failover.
            credentials=config.get("credentials"),
            pool_name=f"zoho:{org_id}" if org_id else "zoho",
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

    def _find_existing_bill(self, invoice_number: str, vendor_id: str) -> Optional[str]:
        """Search Zoho for a bill with the given invoice_number (bill_number).

        Returns the Zoho bill_id string if found, None otherwise.
        This is used for pre-push idempotency — if a bill already exists we return
        its ID immediately rather than creating a duplicate.
        """
        if not invoice_number:
            return None
        try:
            bill = self.client.find_bill_by_number(invoice_number)
            if bill:
                bill_id = bill.get("bill_id")
                if bill_id:
                    logger.info(
                        "Pre-push idempotency check: bill '%s' already exists in Zoho (bill_id=%s)",
                        invoice_number, bill_id,
                    )
                    return bill_id
        except Exception as e:
            # Log and continue — a search failure should not block the push attempt
            logger.warning("Pre-push existence check failed for bill '%s': %s", invoice_number, e)
        return None

    def push_bill(self, draft: Any, db: Session) -> Dict[str, Any]:
        # GST handling: tax_id is set on each line item; Zoho automatically computes
        # CGST/SGST/IGST based on its configured tax rates (Option A — Zoho-managed taxes).
        # Configure the tax_id via the Zoho integration settings in the UI.
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

        # Pre-push idempotency check — return immediately if bill already exists in Zoho.
        # Prevents duplicate bills when the DB update fails after a successful Zoho create
        # and the user retries the push.
        invoice_number = (draft.invoice_number or "").strip()
        existing_bill_id = self._find_existing_bill(invoice_number, vendor_id)
        if existing_bill_id:
            return {"external_id": existing_bill_id, "platform": "zoho"}

        # Resolve COA → Zoho account IDs
        from app.platforms.account_resolver import resolve_accounts_for_platform
        accounts = resolve_accounts_for_platform(draft, "zoho", db)

        # Fail fast if no account can be resolved for any line item.
        # A bill is pushable if: any HSN is mapped, OR a draft-level account exists,
        # OR the integration has a default_account_id.
        has_hsn_match = bool(accounts and accounts.hsn_account_map)
        has_draft_account = bool(accounts and accounts.main_account_ref)
        has_default = bool(self.client.default_account_id)
        if not (has_hsn_match or has_draft_account or has_default):
            raise Exception(
                "No Chart of Accounts mapping found for this bill. "
                "Go to Chart of Accounts, tag the relevant account with the HSN/SAC codes from this invoice, "
                "or set a Default Account ID in Integrations → Zoho Books."
            )

        tax_id = self.config.get("tax_id") or ""
        igst_tax_id = self.config.get("igst_tax_id") or ""
        org_state_code = (self.config.get("org_state_code") or "").strip()

        # GST routing: inter-state → IGST; intra-state → CGST+SGST.
        # The correct comparator is vendor state vs BUYER state (buyer_gst_number[:2]).
        # org_state_code is only used as a fallback when buyer GSTIN is absent.
        # Using org_state_code as the buyer state causes false intra-state matches when
        # the vendor and org happen to be in the same state (e.g. both TN) even though
        # the actual buyer is in a different state (e.g. KA).
        vendor_gst = (getattr(invoice, "gst_number", None) or "").strip()
        buyer_gst = (getattr(invoice, "buyer_gst_number", None) or "").strip()
        vendor_state = vendor_gst[:2] if len(vendor_gst) >= 2 else ""
        buyer_state = buyer_gst[:2] if len(buyer_gst) >= 2 else org_state_code

        if vendor_state and buyer_state:
            is_interstate = vendor_state != buyer_state
            chosen_tax_id = igst_tax_id if is_interstate else tax_id
            logger.info(
                "GST route: vendor_state=%s buyer_state=%s (from %s) → %s → using tax_id=%s",
                vendor_state, buyer_state,
                "buyer_gst_number" if (len(buyer_gst) >= 2) else "org_state_code fallback",
                "IGST (inter-state)" if is_interstate else "CGST+SGST (intra-state)",
                chosen_tax_id,
            )
        else:
            # Cannot determine routing — default to intra-state, let Zoho's error retry handle it
            chosen_tax_id = tax_id
            logger.info("Cannot determine GST route (vendor_state=%r buyer_state=%r) — defaulting to intra-state", vendor_state, buyer_state)

        def _try_push(use_tax_id: str) -> dict:
            payload = invoice_to_zoho_bill(
                invoice, vendor_id,
                accounts=accounts,
                fallback_account_id=self.client.default_account_id,
                tax_id=use_tax_id or None,
                tds_tax_id=accounts.tds_tax_id if accounts else None,
                draft=draft,
            )
            return self.client.create_bill(payload)

        from app.core.exceptions import ZohoError
        try:
            result = _try_push(chosen_tax_id)
        except ZohoError as e:
            msg = str(e).lower()
            if "igst has to be applied" in msg and igst_tax_id:
                # Zoho says this is inter-state but we sent intra-state → retry with IGST
                logger.info("Retrying with IGST tax_id=%s (inter-state)", igst_tax_id)
                try:
                    result = _try_push(igst_tax_id)
                except ZohoError as e2:
                    if "already been created" in str(e2).lower():
                        bill_number = invoice.invoice_number or f"BILL-{invoice.id}"
                        existing = self.client.find_bill_by_number(bill_number)
                        if existing:
                            logger.info("Bill already in Zoho: %s", existing.get("bill_id"))
                            return {"external_id": existing["bill_id"], "platform": "zoho"}
                    raise
            elif "igst cannot be applied" in msg or "intrastate" in msg:
                # Zoho says this is intra-state but we sent IGST → retry with CGST+SGST
                logger.info(
                    "Retrying with CGST+SGST tax_id=%s (intra-state — org_state_code mismatch, "
                    "check your Zoho integration settings)",
                    tax_id,
                )
                result = _try_push(tax_id)
            elif "already been created" in msg:
                bill_number = invoice.invoice_number or f"BILL-{invoice.id}"
                existing = self.client.find_bill_by_number(bill_number)
                if existing:
                    logger.info("Bill already in Zoho (dedup): %s", existing.get("bill_id"))
                    return {"external_id": existing["bill_id"], "platform": "zoho"}
                raise
            else:
                raise

        bill = result.get("bill", {})
        return {"external_id": bill.get("bill_id", ""), "platform": "zoho"}

    def delete_bill(self, bill_id: str) -> None:
        """Delete a bill in Zoho Books. Raises ZohoError on failure."""
        self.client.delete_bill(bill_id)

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

    def list_tds_taxes(self) -> List[Dict[str, Any]]:
        """Fetch TDS tax masters from Zoho Books India.

        The client hits /settings/taxes?is_tds_request=true, which returns
        Direct-Taxes / Income-TDS rows with tax_type='tds_tax'. Section codes
        live inside the tax_name (e.g. "(Section 194 J)"); we normalise that to
        "194J". Rate is on `tax_percentage`.
        """
        import re
        try:
            rows = self.client.list_tds_taxes()
        except Exception as e:
            logger.error("Failed to list Zoho TDS taxes: %s", e)
            return []

        # Match "194", "194 J", "194J", "194-J", "192B", "206C", etc.
        section_re = re.compile(r"\b(19[2-6]|20[6-7])\s*[\- ]?\s*([A-Z]{1,2})?\b")
        results: List[Dict[str, Any]] = []
        for t in rows:
            ttype = (t.get("tax_type") or "").lower()
            name = t.get("tax_name") or t.get("name") or ""
            # Trust Zoho's own tag first; otherwise heuristic on name.
            is_tds = ttype == "tds_tax" or "tds" in name.lower() or "194" in name or "tcs" in name.lower()
            if not is_tds:
                continue
            section = None
            m = section_re.search(name.upper())
            if m:
                section = (m.group(1) + (m.group(2) or "")).strip()
            try:
                rate = float(t.get("tax_percentage") or t.get("rate") or 0) or None
            except (TypeError, ValueError):
                rate = None
            results.append({
                "id": str(t.get("tax_id") or t.get("id") or ""),
                "name": name,
                "section": section,
                "rate": rate,
                "tax_type": "tds",
                "is_active": not bool(t.get("is_inactive", False)) and bool(t.get("is_active", True)),
                "raw": t,
            })
        return results

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
        from app.utils.vendor_name_utils import is_match
        try:
            # Try exact search first
            contacts = self.client.list_contacts(contact_name=vendor_name)
            for c in contacts:
                if c.get("contact_name", "").lower() == vendor_name.lower():
                    return c["contact_id"]
            # Fuzzy: fetch all vendors, normalise and compare
            all_contacts = self.client.list_contacts()
            for c in all_contacts:
                if is_match(c.get("contact_name", ""), vendor_name):
                    logger.info("Fuzzy vendor match: '%s' → '%s'", vendor_name, c.get("contact_name"))
                    return c["contact_id"]
        except Exception as e:
            logger.warning("Zoho vendor search failed: %s", e)
        return None

    def create_vendor(self, vendor_name: str, **kwargs) -> str:
        payload = build_vendor_payload(
            vendor_name,
            gst_number=kwargs.get("gst_number"),
            pan_number=kwargs.get("pan_number"),
            address=kwargs.get("address"),
        )
        result = self.client.create_contact(payload)
        return result.get("contact", {}).get("contact_id", "")

    @classmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        return [
            {"key": "client_id", "label": "Client ID", "type": "text", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password", "required": True},
            {"key": "redirect_uri", "label": "Redirect URI", "type": "text", "required": True,
             "help": "Must match exactly what you registered in the Zoho API Console. "
                     "Use: http://localhost:8000/api/integrations/zoho/oauth/callback"},
            {"key": "refresh_token", "label": "Refresh Token", "type": "password", "required": False,
             "help": "Auto-filled after you click 'Authorise with Zoho'. Leave blank before authorising."},
            {"key": "organization_id", "label": "Organization ID", "type": "text", "required": True},
            {"key": "base_url", "label": "API Base URL", "type": "text", "required": True,
             "default": "https://www.zohoapis.in/books/v3"},
            {"key": "auth_url", "label": "Auth URL", "type": "text", "required": True,
             "default": "https://accounts.zoho.in/oauth/v2/token"},
            {"key": "default_account_id", "label": "Default Account ID (Chart of Accounts)", "type": "text",
             "required": False},
            {"key": "tax_id", "label": "GST Tax ID — Intra-state (CGST+SGST)", "type": "text",
             "required": False,
             "help": "Zoho tax rate ID for intra-state purchases (auto-splits into CGST+SGST). "
                     "Find in Zoho Books → Settings → Taxes."},
            {"key": "igst_tax_id", "label": "IGST Tax ID — Inter-state", "type": "text",
             "required": False,
             "help": "Zoho tax rate ID for inter-state purchases (IGST). "
                     "Auto-selected when vendor state differs from org state."},
            {"key": "org_state_code", "label": "Organisation State Code", "type": "text",
             "required": False,
             "help": "2-digit GST state code of your organisation (e.g. 29 = Karnataka, 33 = Tamil Nadu). "
                     "Used to auto-detect inter-state vs intra-state for every vendor bill. "
                     "If set, IGST is used when the vendor's state differs from this; CGST+SGST otherwise."},
        ]
