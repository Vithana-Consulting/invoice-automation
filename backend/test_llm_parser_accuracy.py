"""
LLM Parser accuracy test — 14 synthetic invoices (A1–N1)
Run from the backend directory:
    python3 test_llm_parser_accuracy.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

# ── Bootstrap ─────────────────────────────────────────────────────────────────
sys.path.insert(0, ".")

# Override settings BEFORE importing anything that reads them
from app.config import settings  # noqa: E402 — must come before other app imports

settings.LLM_PROVIDER = os.environ.get("LLM_PROVIDER", settings.LLM_PROVIDER)
settings.LLM_MODEL = os.environ.get("LLM_MODEL", settings.LLM_MODEL)
# API key must come from .env or environment — never hardcoded

from app.parsers.llm_parser import LLMParser  # noqa: E402

# ── Ground truth ───────────────────────────────────────────────────────────────
GT_PATH = "data/test_invoices/ground_truth.json"
INVOICE_DIR = "data/test_invoices"
FIELDS = ["vendor_name", "vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date", "total_amount"]

with open(GT_PATH) as f:
    ground_truth = json.load(f)

# ── Date normaliser ────────────────────────────────────────────────────────────
DATE_FORMATS = [
    "%d/%m/%Y",   # 15/03/2025
    "%d %b %Y",   # 01 Mar 2025  /  28 Feb 2025  /  12-Jan-2025 (after strip)
    "%Y-%m-%d",   # 2025-01-20
    "%d-%m-%Y",   # 05-02-2025
    "%d-%b-%Y",   # 12-Jan-2025
]

def normalise_date(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw  # return as-is if nothing matched


# ── Comparison helpers ─────────────────────────────────────────────────────────
def compare_field(field: str, actual, expected) -> bool:
    if field == "vendor_name":
        if actual is None or expected is None:
            return actual == expected
        return actual.strip().upper() == expected.strip().upper()

    if field in ("vendor_gstin", "buyer_gstin"):
        # both None → pass; one None → fail
        if expected is None and actual is None:
            return True
        if expected is None or actual is None:
            return False
        return str(actual).strip() == str(expected).strip()

    if field == "invoice_number":
        if actual is None or expected is None:
            return actual == expected
        return str(actual).strip().upper() == str(expected).strip().upper()

    if field == "invoice_date":
        norm_expected = normalise_date(str(expected)) if expected else None
        norm_actual = normalise_date(str(actual)) if actual else None
        return norm_actual == norm_expected

    if field == "total_amount":
        try:
            return abs(float(actual) - float(expected)) <= 1.0
        except (TypeError, ValueError):
            return False

    return actual == expected


def get_invoice_field(invoice, field: str):
    """Map ground-truth field names to Invoice object attributes."""
    mapping = {
        "vendor_name": "vendor_name",
        "vendor_gstin": "gst_number",
        "buyer_gstin": "buyer_gst_number",
        "invoice_number": "invoice_number",
        "invoice_date": "date",
        "total_amount": "total_amount",
    }
    attr = mapping.get(field, field)
    return getattr(invoice, attr, None)


# ── Main test loop ─────────────────────────────────────────────────────────────
parser = LLMParser()
invoices = sorted(ground_truth.keys())

field_pass = {f: 0 for f in FIELDS}
field_total = {f: 0 for f in FIELDS}
invoice_pass = 0

PASS = "✓"
FAIL = "✗"

print("=" * 72)
print(f"  LLM Parser Accuracy Test  —  {len(invoices)} invoices  —  GPT-4o vision")
print("=" * 72)

for filename in invoices:
    pdf_path = os.path.join(INVOICE_DIR, filename)
    gt = ground_truth[filename]

    print(f"\n[{filename}]", flush=True)

    try:
        invoice = parser.parse(pdf_path, "pdf")
    except Exception as exc:
        print(f"  ERROR parsing: {exc}")
        # Count all fields as failed
        for f in FIELDS:
            field_total[f] += 1
        continue

    all_ok = True
    for field in FIELDS:
        expected = gt.get(field)
        actual = get_invoice_field(invoice, field)
        ok = compare_field(field, actual, expected)
        field_total[field] += 1
        if ok:
            field_pass[field] += 1
            mark = PASS
        else:
            all_ok = False
            mark = FAIL

        if ok:
            print(f"  {mark} {field}")
        else:
            norm_exp = normalise_date(str(expected)) if field == "invoice_date" else expected
            print(f"  {mark} {field}")
            print(f"      expected : {norm_exp!r}")
            print(f"      got      : {actual!r}")

    if all_ok:
        invoice_pass += 1


# ── Summary table ──────────────────────────────────────────────────────────────
total_fields_checked = sum(field_total.values())
total_fields_passed = sum(field_pass.values())

print("\n" + "=" * 72)
print("  FIELD-BY-FIELD ACCURACY SUMMARY")
print("=" * 72)
print(f"  {'Field':<22}  {'Pass':>4} / {'Total':>5}   {'Accuracy':>8}")
print(f"  {'-'*22}  {'-'*4}   {'-'*5}   {'-'*8}")
for field in FIELDS:
    p = field_pass[field]
    t = field_total[field]
    pct = (p / t * 100) if t else 0
    bar = PASS if p == t else ("~" if p > 0 else FAIL)
    print(f"  {bar} {field:<21}  {p:>4} / {t:>5}   {pct:>7.1f}%")

print()
overall_field_pct = (total_fields_passed / total_fields_checked * 100) if total_fields_checked else 0
overall_invoice_pct = (invoice_pass / len(invoices) * 100) if invoices else 0

print(f"  Overall field accuracy  : {total_fields_passed}/{total_fields_checked}  ({overall_field_pct:.1f}%)")
print(f"  Overall invoice accuracy: {invoice_pass}/{len(invoices)}  ({overall_invoice_pct:.1f}%)  [all 6 fields correct]")
print("=" * 72)

target = 95.0
status = "PASS" if overall_field_pct >= target else "FAIL"
print(f"\n  Target: >=95%  |  Result: {overall_field_pct:.1f}%  |  STATUS: {status}")
print()
