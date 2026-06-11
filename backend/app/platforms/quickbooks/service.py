from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.platforms.base import BillingPlatform, register_billing
from app.platforms.quickbooks.client import QuickBooksAuth, QuickBooksClient

logger = logging.getLogger(__name__)

# QuickBooks DocNumber has a hard 21-character limit (Intuit Bill API spec).
QBO_DOC_NUMBER_MAX = 21


def _to_qbo_date(date_str: Optional[str]) -> Optional[str]:
    """Normalize a stored date string to QBO's required ``YYYY-MM-DD`` format.

    QuickBooks Date fields (TxnDate, DueDate) must be ISO-8601 dates. Drafts may
    carry dates as ``YYYY-MM-DD`` or ``DD/MM/YYYY`` (India convention) depending
    on what the parser extracted, so normalize before sending. Returns None when
    the value is empty or unparseable (caller then omits the field).
    """
    if not date_str:
        return None
    s = str(date_str).strip()
    if re.match(r"\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return None


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
        # Home currency of the QBO company account (set once during company setup in QBO).
        # For Indian companies this is INR. Bills in the home currency need no CurrencyRef.
        # Bills in any other currency are "foreign currency" and require multicurrency to be
        # enabled in QBO Company Settings and also require an ExchangeRate in the payload.
        self.home_currency = (config.get("home_currency") or "INR").upper()

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

        payload = self.build_bill_payload(draft, vendor_ref, accounts)

        result = self.client.create_bill(payload)
        bill = result.get("Bill", {})
        return {"external_id": str(bill.get("Id", "")), "platform": "quickbooks"}

    def build_bill_payload(self, draft: Any, vendor_ref: str,
                           accounts: Any) -> Dict[str, Any]:
        """Build the QBO create-bill payload from a draft + resolved accounts.

        Pure (no DB/network) so it is unit-testable. The core invariant it
        guarantees: the bill's Line amounts always sum to the invoice total —
        QBO derives TotalAmt from that sum, so any drift would post a wrong total.
        """
        main_account_ref = accounts.main_account_ref
        if not main_account_ref:
            # Never silently post to an arbitrary account — that books the bill to
            # the wrong GL. Fail loudly so the operator assigns/configures one.
            raise Exception(
                "No expense account resolved for this bill on QuickBooks. Assign a "
                "GL account on the draft, or configure a default PURCHASE account "
                "in Chart of Accounts, before pushing."
            )
        amount = float(draft.total_amount) if draft.total_amount else 0.0

        # Build separate GST input lines. QBO derives the bill TotalAmt as the sum
        # of all lines, so the main expense line must equal (total − tax we
        # actually post). A tax component is emitted as its own line only when BOTH
        # its amount AND its resolved COA account exist; otherwise it stays folded
        # into the main line so the bill still reconciles to the invoice total
        # (rather than understating it, which was the prior bug).
        tax_lines = []
        emitted_tax = 0.0
        for amount_attr, ref_attr, label in (
            ("cgst_amount", "cgst_account_ref", "CGST"),
            ("sgst_amount", "sgst_account_ref", "SGST"),
            ("igst_amount", "igst_account_ref", "IGST"),
        ):
            tax_amt = getattr(accounts, amount_attr) or 0
            tax_ref = getattr(accounts, ref_attr)
            if tax_amt and tax_ref:
                rounded = round(float(tax_amt), 2)
                tax_lines.append({
                    "Amount": rounded,
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "AccountBasedExpenseLineDetail": {"AccountRef": {"value": tax_ref}},
                    "Description": label,
                })
                emitted_tax += rounded
            elif tax_amt and not tax_ref:
                logger.warning(
                    "[QBO] %s amount %.2f present but no COA tax account resolved "
                    "for QuickBooks — folding it into the main expense line so the "
                    "bill reconciles. Configure a default %s account in Chart of "
                    "Accounts to post it separately.",
                    label, float(tax_amt), label,
                )

        main_amount = round(amount - emitted_tax, 2)

        lines = [{
            "Amount": main_amount,
            "DetailType": "AccountBasedExpenseLineDetail",
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": main_account_ref},
            },
            "Description": f"Invoice {draft.invoice_number or draft.id}",
        }]
        lines.extend(tax_lines)

        # DocNumber is capped at 21 chars by QBO — truncate to avoid a push failure.
        doc_number = (draft.invoice_number or f"BILL-{draft.id}")[:QBO_DOC_NUMBER_MAX]

        payload = {
            "VendorRef": {"value": vendor_ref},
            "Line": lines,
            "DocNumber": doc_number,
        }

        # Currency handling per QBO API spec:
        # - Home currency bills: omit CurrencyRef (QBO defaults to home currency).
        # - Foreign currency bills: CurrencyRef + ExchangeRate are both required by QBO.
        #   QBO also requires multicurrency to be enabled in Company Settings > Advanced.
        currency = (draft.currency or self.home_currency).upper()
        if currency != self.home_currency:
            payload["CurrencyRef"] = {"value": currency}
            # ExchangeRate is required by QBO for foreign currency bills.
            # Source: invoice exchange_rate field if set, else config default, else hard error.
            exchange_rate = (
                getattr(draft, "exchange_rate", None)
                or self.config.get("default_exchange_rate")
            )
            if not exchange_rate:
                raise Exception(
                    f"Bill currency is {currency} but QBO home currency is {self.home_currency}. "
                    "QuickBooks requires an ExchangeRate for foreign currency bills. "
                    "Set 'default_exchange_rate' in the QuickBooks integration config "
                    f"(e.g. 1 {currency} = X {self.home_currency}), or enable multicurrency "
                    "in QBO Company Settings > Advanced and supply an exchange rate."
                )
            payload["ExchangeRate"] = float(exchange_rate)

        txn_date = _to_qbo_date(draft.invoice_date)
        if txn_date:
            payload["TxnDate"] = txn_date
        due_date = _to_qbo_date(draft.due_date)
        if due_date:
            payload["DueDate"] = due_date

        return payload

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
            {"key": "redirect_uri", "label": "Redirect URI", "type": "text", "required": True,
             "default": "http://localhost:8000/api/integrations/quickbooks/oauth/callback",
             "description": (
                 "Must match a Redirect URI registered in your Intuit app "
                 "(Developer Portal > Keys & OAuth). Used by the 'Authorise with QuickBooks' button."
             )},
            {"key": "refresh_token", "label": "Refresh Token", "type": "password", "required": False,
             "description": (
                 "Leave blank — auto-filled after you click 'Authorise with QuickBooks'. "
                 "Only set manually if you generated a token via the Intuit OAuth Playground."
             )},
            {"key": "realm_id", "label": "Realm ID (Company ID)", "type": "text", "required": False,
             "description": (
                 "Leave blank — auto-filled from the OAuth callback after authorising. "
                 "Set manually only if connecting without the Authorise button."
             )},
            {"key": "base_url", "label": "API Base URL", "type": "text", "required": True,
             "default": "https://sandbox-quickbooks.api.intuit.com"},
            {
                "key": "home_currency",
                "label": "Home Currency",
                "type": "text",
                "required": False,
                "default": "INR",
                "description": (
                    "ISO 4217 code of your QBO company's home currency (e.g. INR, USD). "
                    "Must match what was set when the QBO company was created — it cannot be "
                    "changed after the fact. Bills in this currency are posted as-is. "
                    "Bills in any other currency require multicurrency to be enabled in "
                    "QBO Company Settings > Advanced, and also require default_exchange_rate."
                ),
            },
            {
                "key": "default_exchange_rate",
                "label": "Default Exchange Rate (foreign currency → home currency)",
                "type": "text",
                "required": False,
                "default": "",
                "description": (
                    "Used only for foreign-currency bills (e.g. USD bills when home currency is INR). "
                    "Enter the rate as: 1 foreign unit = X home currency units "
                    "(e.g. enter 84.5 if 1 USD = 84.50 INR). "
                    "Requires multicurrency to be enabled in QBO first. "
                    "Leave blank if all your bills are in the home currency."
                ),
            },
        ]
