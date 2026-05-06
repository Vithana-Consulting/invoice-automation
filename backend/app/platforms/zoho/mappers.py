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
    tax_id: Optional[str] = None,
) -> dict:
    """Map an InvoiceRecord to Zoho Books create-bill payload.

    Account resolution priority per line item:
      1. HSN/SAC code match in accounts.hsn_account_map
      2. Draft-level COA account (accounts.main_account_ref)
      3. Fallback account_id from Zoho integration config
    """
    # Draft-level fallback account
    draft_account_id = ""
    if accounts and accounts.main_account_ref:
        draft_account_id = accounts.main_account_ref
    elif fallback_account_id:
        draft_account_id = fallback_account_id

    hsn_map = (accounts.hsn_account_map or {}) if accounts else {}

    # Build line items from invoice
    line_items_raw = []
    if invoice.line_items_json:
        try:
            line_items_raw = json.loads(invoice.line_items_json)
        except json.JSONDecodeError:
            pass

    zoho_items = []
    for item in line_items_raw:
        hsn = (item.get("hsn_or_sac") or item.get("hsn_sac_code") or item.get("hsn_code") or "").strip()
        # Per-line account: HSN match → draft-level → integration fallback
        line_account_id = hsn_map.get(hsn) or draft_account_id

        description = item.get("description") or "Invoice item"
        zi = {
            "name": description,
            "description": description,
            "rate": item.get("unit_price") or item.get("amount", 0),
            "quantity": item.get("quantity", 1) or 1,
        }
        if hsn:
            zi["hsn_or_sac"] = hsn
        if line_account_id:
            zi["account_id"] = line_account_id
        # Zoho computes CGST/SGST/IGST automatically from this tax_id
        if tax_id:
            zi["tax_id"] = tax_id
        zoho_items.append(zi)

    if not zoho_items:
        amount = float(invoice.total_amount) if invoice.total_amount else 0.0
        fallback_name = f"Invoice {invoice.invoice_number or invoice.file_name or 'item'}"
        zi = {
            "name": fallback_name,
            "description": fallback_name,
            "rate": amount,
            "quantity": 1,
        }
        if draft_account_id:
            zi["account_id"] = draft_account_id
        if tax_id:
            zi["tax_id"] = tax_id
        zoho_items.append(zi)

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

    # Note: place_of_supply is NOT sent to Zoho for bills — it is a sales invoice
    # field only. Zoho derives supply type (IGST vs CGST+SGST) from vendor GST state
    # vs org state, which is handled via tax_id / igst_tax_id selection above.

    payload["notes"] = f"Auto-imported from invoice {invoice.invoice_number or invoice.file_name}"
    return payload


def build_vendor_payload(vendor_name: str, gst_number: str = None,
                         pan_number: str = None, address: str = None) -> dict:
    payload = {"contact_name": vendor_name, "contact_type": "vendor"}

    if gst_number:
        payload["gst_no"] = gst_number
        # "business_gst" = Registered Business - Regular
        # Zoho auto-derives source_of_supply from the GST state code
        payload["gst_treatment"] = "business_gst"

    if pan_number:
        payload["pan_no"] = pan_number

    if address:
        payload["billing_address"] = {"address": address}

    return payload
