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


def _pick(draft, invoice, field):
    """Prefer the draft's value (user-edited), fall back to invoice (LLM-extracted)."""
    val = getattr(draft, field, None) if draft is not None else None
    if val not in (None, ""):
        return val
    return getattr(invoice, field, None)


def invoice_to_zoho_bill(
    invoice,
    vendor_id: str,
    accounts: Optional[ResolvedAccounts] = None,
    fallback_account_id: str = "",
    tax_id: Optional[str] = None,
    tds_tax_id: Optional[str] = None,
    draft=None,
) -> dict:
    """Map an InvoiceRecord (and optional InvoiceDraft) to a Zoho Books create-bill payload.

    Field source priority — draft first, invoice as fallback:
      invoice_number, invoice_date, due_date, total_amount, line_items_json
    Read from `invoice` only: buyer_gst_number, gst_number, file_name, id.

    Account resolution priority per line item:
      1. HSN/SAC code match in accounts.hsn_account_map
      2. Draft-level COA account (accounts.main_account_ref)
      3. Fallback account_id from Zoho integration config

    TDS is bill-level. When tds_tax_id is provided (or carried on `accounts`),
    Zoho computes the withhold amount from its rate — we never compute it here.
    """
    # Draft-level fallback account
    draft_account_id = ""
    if accounts and accounts.main_account_ref:
        draft_account_id = accounts.main_account_ref
    elif fallback_account_id:
        draft_account_id = fallback_account_id

    hsn_map = (accounts.hsn_account_map or {}) if accounts else {}

    invoice_number = _pick(draft, invoice, "invoice_number")
    invoice_date = _pick(draft, invoice, "invoice_date")
    due_date = _pick(draft, invoice, "due_date")
    total_amount = _pick(draft, invoice, "total_amount")
    line_items_json = _pick(draft, invoice, "line_items_json")

    # Build line items — prefer the draft's edited line items
    line_items_raw = []
    if line_items_json:
        try:
            line_items_raw = json.loads(line_items_json)
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
        amount = float(total_amount) if total_amount else 0.0
        fallback_name = f"Invoice {invoice_number or invoice.file_name or 'item'}"
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
        "bill_number": invoice_number or f"BILL-{invoice.id}",
        "reference_number": invoice_number,
        "line_items": zoho_items,
    }

    d = to_zoho_date(invoice_date)
    if d:
        payload["date"] = d
    d = to_zoho_date(due_date)
    if d:
        payload["due_date"] = d

    # destination_of_supply tells Zoho the buyer's state so it can correctly route
    # IGST (inter-state) vs CGST+SGST (intra-state) for bills.
    # Derived from buyer_gst_number (first 2 digits = state code).
    buyer_gst = (getattr(invoice, "buyer_gst_number", None) or "").strip()
    if len(buyer_gst) >= 2:
        buyer_state_name = _gst_state_code_to_name(buyer_gst[:2])
        if buyer_state_name:
            payload["destination_of_supply"] = buyer_state_name

    # TDS — bill-level. Explicit tds_tax_id arg wins, else fall back to accounts.tds_tax_id.
    resolved_tds = tds_tax_id or (accounts.tds_tax_id if accounts else None)
    if resolved_tds:
        payload["tds_tax_id"] = resolved_tds

    payload["notes"] = f"Auto-imported from invoice {invoice_number or invoice.file_name}"
    return payload


# GST state code → Zoho 2-letter state abbreviation (used for destination_of_supply)
_GST_STATE_MAP = {
    "01": "JK", "02": "HP", "03": "PB", "04": "CH", "05": "UT", "06": "HR",
    "07": "DL", "08": "RJ", "09": "UP", "10": "BR", "11": "SK", "12": "AR",
    "13": "NL", "14": "MN", "15": "MZ", "16": "TR", "17": "ML", "18": "AS",
    "19": "WB", "20": "JH", "21": "OR", "22": "CG", "23": "MP", "24": "GJ",
    "25": "DD", "26": "DN", "27": "MH", "28": "AP", "29": "KA", "30": "GA",
    "31": "LD", "32": "KL", "33": "TN", "34": "PY", "35": "AN", "36": "TG",
    "37": "AP", "38": "LA", "97": "OT", "99": "CJ",
}


def _gst_state_code_to_name(code: str) -> Optional[str]:
    return _GST_STATE_MAP.get(code.zfill(2))


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
