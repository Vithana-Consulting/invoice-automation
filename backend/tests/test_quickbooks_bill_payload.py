"""Unit tests for the QuickBooks create-bill payload builder.

These guard the invariant that broke before: QBO derives a bill's TotalAmt from
the sum of its Line amounts, so the lines must ALWAYS sum to the invoice total —
even when a GST component has no resolved COA account (it must then fold into the
main line rather than silently vanish, which understated the bill).

Also covers the other doc-driven fixes: DocNumber truncation (21-char cap),
date normalization (YYYY-MM-DD), the no-account hard error, and foreign-currency
ExchangeRate handling.

Pure tests — build_bill_payload touches no DB or network.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.platforms.account_resolver import ResolvedAccounts
from app.platforms.quickbooks.service import QuickBooksBilling


def _billing(home_currency: str = "INR", **config) -> QuickBooksBilling:
    return QuickBooksBilling({"home_currency": home_currency, **config})


def _draft(**kw) -> SimpleNamespace:
    base = dict(
        id=1,
        invoice_number="INV-2025-001",
        invoice_date="2025-12-01",
        due_date="2025-12-31",
        total_amount=11800,
        currency="INR",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _sum_lines(payload: dict) -> float:
    return round(sum(line["Amount"] for line in payload["Line"]), 2)


# ─── The core invariant: lines always reconcile to the total ─────────────────

def test_lines_sum_to_total_with_all_tax_accounts():
    """Intra-state bill: CGST+SGST each post to their own line."""
    accounts = ResolvedAccounts(
        main_account_ref="ACC_EXPENSE",
        cgst_amount=900, cgst_account_ref="ACC_CGST",
        sgst_amount=900, sgst_account_ref="ACC_SGST",
    )
    payload = _billing().build_bill_payload(_draft(total_amount=11800), "V1", accounts)

    assert _sum_lines(payload) == 11800
    assert len(payload["Line"]) == 3           # main + CGST + SGST
    assert payload["Line"][0]["Amount"] == 10000  # main = total − tax


def test_lines_sum_to_total_when_a_tax_account_is_missing():
    """THE REGRESSION: SGST amount present but no COA account → it must fold into
    the main line, not disappear. Lines must still sum to the full total."""
    accounts = ResolvedAccounts(
        main_account_ref="ACC_EXPENSE",
        cgst_amount=900, cgst_account_ref="ACC_CGST",
        sgst_amount=900, sgst_account_ref=None,   # unmapped
    )
    payload = _billing().build_bill_payload(_draft(total_amount=11800), "V1", accounts)

    assert _sum_lines(payload) == 11800           # <- understated before the fix
    assert len(payload["Line"]) == 2              # main + CGST only
    assert payload["Line"][0]["Amount"] == 10900  # main absorbed the 900 SGST


def test_lines_sum_to_total_when_no_tax_accounts_at_all():
    accounts = ResolvedAccounts(
        main_account_ref="ACC_EXPENSE",
        cgst_amount=900, cgst_account_ref=None,
        sgst_amount=900, sgst_account_ref=None,
    )
    payload = _billing().build_bill_payload(_draft(total_amount=11800), "V1", accounts)

    assert _sum_lines(payload) == 11800
    assert len(payload["Line"]) == 1
    assert payload["Line"][0]["Amount"] == 11800


def test_lines_sum_to_total_interstate_igst():
    accounts = ResolvedAccounts(
        main_account_ref="ACC_EXPENSE",
        igst_amount=1800, igst_account_ref="ACC_IGST",
    )
    payload = _billing().build_bill_payload(_draft(total_amount=11800), "V1", accounts)

    assert _sum_lines(payload) == 11800
    assert len(payload["Line"]) == 2
    assert payload["Line"][1]["Description"] == "IGST"


def test_lines_sum_to_total_no_tax_lines():
    accounts = ResolvedAccounts(main_account_ref="ACC_EXPENSE")
    payload = _billing().build_bill_payload(_draft(total_amount=5000), "V1", accounts)

    assert _sum_lines(payload) == 5000
    assert len(payload["Line"]) == 1


def test_lines_sum_to_total_with_fractional_amounts():
    """Independent rounding of lines must not drift from the total."""
    accounts = ResolvedAccounts(
        main_account_ref="ACC_EXPENSE",
        cgst_amount=90.04, cgst_account_ref="ACC_CGST",
        sgst_amount=90.04, sgst_account_ref="ACC_SGST",
    )
    payload = _billing().build_bill_payload(_draft(total_amount=1180.50), "V1", accounts)

    assert _sum_lines(payload) == pytest.approx(1180.50, abs=0.01)


# ─── DocNumber 21-char cap ───────────────────────────────────────────────────

def test_doc_number_truncated_to_21_chars():
    long_no = "INV/2025-26/PROFESSIONAL-SERVICES/0001"  # > 21 chars
    payload = _billing().build_bill_payload(
        _draft(invoice_number=long_no), "V1", ResolvedAccounts(main_account_ref="A"),
    )
    assert len(payload["DocNumber"]) == 21
    assert payload["DocNumber"] == long_no[:21]


def test_doc_number_short_is_unchanged():
    payload = _billing().build_bill_payload(
        _draft(invoice_number="INV-001"), "V1", ResolvedAccounts(main_account_ref="A"),
    )
    assert payload["DocNumber"] == "INV-001"


# ─── Date normalization to YYYY-MM-DD ────────────────────────────────────────

def test_dates_normalized_from_ddmmyyyy():
    payload = _billing().build_bill_payload(
        _draft(invoice_date="01/12/2025", due_date="31/12/2025"),
        "V1", ResolvedAccounts(main_account_ref="A"),
    )
    assert payload["TxnDate"] == "2025-12-01"
    assert payload["DueDate"] == "2025-12-31"


def test_dates_already_iso_pass_through():
    payload = _billing().build_bill_payload(
        _draft(invoice_date="2025-12-01"),
        "V1", ResolvedAccounts(main_account_ref="A"),
    )
    assert payload["TxnDate"] == "2025-12-01"


def test_unparseable_date_is_omitted():
    payload = _billing().build_bill_payload(
        _draft(invoice_date="Dec 1 2025", due_date=None),
        "V1", ResolvedAccounts(main_account_ref="A"),
    )
    assert "TxnDate" not in payload
    assert "DueDate" not in payload


# ─── No expense account → hard error (never post to a guessed account) ───────

def test_missing_main_account_raises():
    with pytest.raises(Exception, match="No expense account resolved"):
        _billing().build_bill_payload(
            _draft(), "V1", ResolvedAccounts(main_account_ref=None),
        )


# ─── Currency handling ───────────────────────────────────────────────────────

def test_home_currency_omits_currency_ref():
    payload = _billing(home_currency="INR").build_bill_payload(
        _draft(currency="INR"), "V1", ResolvedAccounts(main_account_ref="A"),
    )
    assert "CurrencyRef" not in payload
    assert "ExchangeRate" not in payload


def test_foreign_currency_requires_exchange_rate():
    with pytest.raises(Exception, match="ExchangeRate"):
        _billing(home_currency="INR").build_bill_payload(
            _draft(currency="USD"), "V1", ResolvedAccounts(main_account_ref="A"),
        )


def test_foreign_currency_with_config_rate():
    payload = _billing(home_currency="INR", default_exchange_rate="84.5").build_bill_payload(
        _draft(currency="USD"), "V1", ResolvedAccounts(main_account_ref="A"),
    )
    assert payload["CurrencyRef"] == {"value": "USD"}
    assert payload["ExchangeRate"] == 84.5
