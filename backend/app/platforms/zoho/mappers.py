from __future__ import annotations

import json
import re
from typing import Optional

from app.platforms.account_resolver import ResolvedAccounts


def to_zoho_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    if re.match(r"\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", date_str)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return None


def invoice_to_zoho_bill(
    invoice,
    vendor_id: str,
    accounts: Optional[ResolvedAccounts] = None,
    fallback_account_id: str = "",
) -> dict:
    """Map an InvoiceRecord to Zoho Books create-bill payload.

    Account resolution priority:
      1. COA-resolved account (accounts.main_account_ref) — from Chart of Accounts
      2. Fallback account_id — from Zoho integration config (legacy)
      3. No account — Zoho uses its default
    """
    account_id = ""
    if accounts and accounts.main_account_ref:
        account_id = accounts.main_account_ref
    elif fallback_account_id:
        account_id = fallback_account_id

    # Build line items from invoice
    line_items_raw = []
    if invoice.line_items_json:
        try:
            line_items_raw = json.loads(invoice.line_items_json)
        except json.JSONDecodeError:
            pass

    zoho_items = []
    for item in line_items_raw:
        zi = {
            "name": item.get("description", "Invoice item"),
            "rate": item.get("unit_price") or item.get("amount", 0),
            "quantity": item.get("quantity", 1) or 1,
        }
        if account_id:
            zi["account_id"] = account_id
        zoho_items.append(zi)

    if not zoho_items:
        amount = float(invoice.total_amount) if invoice.total_amount else 0.0
        zoho_items.append({
            "name": f"Invoice {invoice.invoice_number or invoice.file_name or 'item'}",
            "rate": amount, "quantity": 1,
            **({"account_id": account_id} if account_id else {}),
        })

    # Note: Zoho Books handles tax via tax_id on line items, not separate line items.
    # Tax is NOT added as separate line items for Zoho (unlike Tally/QuickBooks).
    # Zoho's tax module manages CGST/SGST/IGST automatically based on GST settings.

    payload = {
        "vendor_id": vendor_id,
        "bill_number": invoice.invoice_number or f"BILL-{invoice.id}",
        "reference_number": invoice.invoice_number,
        "line_items": zoho_items,
    }

    d = to_zoho_date(invoice.invoice_date)
    if d:
        payload["date"] = d
    d = to_zoho_date(invoice.due_date)
    if d:
        payload["due_date"] = d

    payload["notes"] = f"Auto-imported from invoice {invoice.invoice_number or invoice.file_name}"
    return payload


def build_vendor_payload(vendor_name: str, gst_number: str = None) -> dict:
    return {"contact_name": vendor_name, "contact_type": "vendor"}
