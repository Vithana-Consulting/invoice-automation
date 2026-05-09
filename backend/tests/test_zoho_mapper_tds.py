"""Unit tests for TDS in the Zoho mapper.

The mapper itself is pure — given a ResolvedAccounts that carries a tds_tax_id,
the bill payload must include tds_tax_id at the bill level (not on line items).
Zoho computes the withhold from the tax record's rate; we never compute it.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.platforms.account_resolver import ResolvedAccounts
from app.platforms.zoho.mappers import invoice_to_zoho_bill


def _fake_invoice() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        invoice_number="INV-2025-001",
        invoice_date="2025-12-01",
        due_date="2025-12-31",
        file_name="invoice.pdf",
        total_amount=65000,
        buyer_gst_number="29AAAAA0000A1Z5",  # Karnataka
        gst_number="33BBBBB0000B1Z2",        # Vendor: Tamil Nadu
        line_items_json=json.dumps([
            {
                "description": "Accounting & Consultancy Charges",
                "hsn_or_sac": "998222",
                "quantity": 1,
                "unit_price": 65000,
            }
        ]),
    )


def test_tds_tax_id_emitted_at_bill_level_via_resolved_accounts():
    invoice = _fake_invoice()
    accounts = ResolvedAccounts(
        main_account_ref="ZOHO_ACC_PROFESSIONAL_FEES",
        tds_section="194J",
        tds_rate=10.0,
        tds_tax_id="ZOHO_TDS_194J_10",
    )
    payload = invoice_to_zoho_bill(invoice, vendor_id="V123", accounts=accounts, tax_id="GST18_ID")

    assert payload["tds_tax_id"] == "ZOHO_TDS_194J_10"
    # Bill-level only — never on line items.
    for li in payload["line_items"]:
        assert "tds_tax_id" not in li


def test_explicit_tds_tax_id_arg_overrides_resolved_accounts():
    invoice = _fake_invoice()
    accounts = ResolvedAccounts(
        main_account_ref="ZOHO_ACC_PROFESSIONAL_FEES",
        tds_tax_id="ZOHO_TDS_FROM_COA",
    )
    payload = invoice_to_zoho_bill(
        invoice, vendor_id="V123", accounts=accounts, tax_id="GST18_ID",
        tds_tax_id="ZOHO_TDS_OVERRIDE",
    )
    assert payload["tds_tax_id"] == "ZOHO_TDS_OVERRIDE"


def test_no_tds_when_unresolved():
    invoice = _fake_invoice()
    accounts = ResolvedAccounts(main_account_ref="ZOHO_ACC_PROFESSIONAL_FEES")
    payload = invoice_to_zoho_bill(invoice, vendor_id="V123", accounts=accounts, tax_id="GST18_ID")
    assert "tds_tax_id" not in payload


def test_gst_line_tax_id_still_emitted_alongside_tds():
    invoice = _fake_invoice()
    accounts = ResolvedAccounts(
        main_account_ref="ZOHO_ACC_PROFESSIONAL_FEES",
        tds_tax_id="ZOHO_TDS_194J_10",
    )
    payload = invoice_to_zoho_bill(invoice, vendor_id="V123", accounts=accounts, tax_id="GST18_ID")
    assert payload["tds_tax_id"] == "ZOHO_TDS_194J_10"
    assert payload["line_items"][0]["tax_id"] == "GST18_ID"


def test_draft_overrides_invoice_for_user_edited_fields():
    invoice = _fake_invoice()  # invoice_number=INV-2025-001, total=65000, date=2025-12-01
    draft = SimpleNamespace(
        invoice_number="INV-2025-001-EDITED",
        invoice_date="2026-01-15",
        due_date="2026-02-15",
        total_amount=70000,
        line_items_json=None,  # falls back to invoice's line items
    )
    accounts = ResolvedAccounts(main_account_ref="ZOHO_ACC")
    payload = invoice_to_zoho_bill(
        invoice, vendor_id="V123", accounts=accounts, tax_id="GST18_ID", draft=draft,
    )
    assert payload["bill_number"] == "INV-2025-001-EDITED"
    assert payload["reference_number"] == "INV-2025-001-EDITED"
    assert payload["date"] == "2026-01-15"
    assert payload["due_date"] == "2026-02-15"
    # Line items pulled from invoice since draft has none
    assert len(payload["line_items"]) == 1


def test_draft_falls_back_to_invoice_when_field_missing():
    invoice = _fake_invoice()
    draft = SimpleNamespace(
        invoice_number=None,    # fall back to invoice
        invoice_date="",        # empty also falls back
        due_date=None,
        total_amount=None,
        line_items_json=None,
    )
    accounts = ResolvedAccounts(main_account_ref="ZOHO_ACC")
    payload = invoice_to_zoho_bill(
        invoice, vendor_id="V123", accounts=accounts, tax_id="GST18_ID", draft=draft,
    )
    assert payload["bill_number"] == "INV-2025-001"
    assert payload["date"] == "2025-12-01"


def test_draft_line_items_override_invoice_line_items():
    invoice = _fake_invoice()
    draft = SimpleNamespace(
        invoice_number=None, invoice_date=None, due_date=None, total_amount=None,
        line_items_json=json.dumps([
            {"description": "Edited line", "hsn_or_sac": "998222", "quantity": 2, "unit_price": 32500},
        ]),
    )
    accounts = ResolvedAccounts(main_account_ref="ZOHO_ACC")
    payload = invoice_to_zoho_bill(
        invoice, vendor_id="V123", accounts=accounts, tax_id="GST18_ID", draft=draft,
    )
    assert len(payload["line_items"]) == 1
    assert payload["line_items"][0]["name"] == "Edited line"
    assert payload["line_items"][0]["quantity"] == 2
