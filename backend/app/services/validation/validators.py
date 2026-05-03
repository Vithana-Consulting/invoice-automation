from __future__ import annotations
import json
from decimal import Decimal
from datetime import date, timedelta
from app.services.validation.base import InvoiceValidator, ValidationResult, Severity


class AmountReconciliationValidator(InvoiceValidator):
    """Line-item subtotal must foot to invoice subtotal within tolerance.

    Expected value priority:
      1. invoice.subtotal — explicitly extracted by LLM from the invoice subtotal field
      2. total_amount - tax_amount — computed fallback when subtotal not available

    Using invoice.subtotal is more reliable because some Indian invoices include
    additional charges (PT, cess) between subtotal and total, making
    total - tax != subtotal.

    Tax-description lines (CGST, SGST, IGST, TDS, etc.) are excluded from the
    line_sum to avoid false failures when the LLM extracts tax rows as line items.
    """
    code = "RECONCILIATION_FAILED"
    TOLERANCE = Decimal("1.00")  # ₹1 rounding tolerance

    # Line item descriptions containing these keywords are skipped from sum
    # (they are tax/charge lines, not service/goods lines)
    TAX_KEYWORDS = {"cgst", "sgst", "igst", "gst", "tds", "cess", "surcharge"}

    def _is_tax_line(self, item: dict) -> bool:
        desc = (item.get("description") or item.get("name") or "").lower()
        return any(kw in desc for kw in self.TAX_KEYWORDS)

    def validate(self, draft, invoice, db) -> ValidationResult:
        total = Decimal(str(draft.total_amount or 0))
        tax   = Decimal(str(draft.tax_amount or 0))
        if total == 0:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No total amount — skipped")

        items = []
        try:
            items = json.loads(invoice.line_items_json or "[]")
        except Exception:
            pass

        if not items:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No line items — skipped")

        # Use invoice.subtotal if LLM extracted it; otherwise fall back to total - tax.
        # When subtotal IS available, trust all line items as-is (they should foot to subtotal).
        # When subtotal is NOT available, filter out obvious standalone tax rows (CGST/SGST/IGST/TDS)
        # to avoid false failures when the LLM double-counts tax as both a line item and tax_breakup.
        extracted_subtotal = Decimal(str(getattr(invoice, "subtotal", None) or 0))
        if extracted_subtotal > 0:
            line_sum = sum(Decimal(str(i.get("amount", 0) or 0)) for i in items)
            expected_subtotal = extracted_subtotal
        else:
            service_items = [i for i in items if not self._is_tax_line(i)]
            items_to_sum = service_items if service_items else items
            line_sum = sum(Decimal(str(i.get("amount", 0) or 0)) for i in items_to_sum)
            expected_subtotal = total - tax

        diff = abs(line_sum - expected_subtotal)

        if diff <= self.TOLERANCE:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK,
                                    f"Line items reconcile (diff ₹{diff:.2f})",
                                    {"line_sum": line_sum, "expected": expected_subtotal, "diff": diff})
        return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                f"Line items (₹{line_sum:.2f}) don't match subtotal (₹{expected_subtotal:.2f}), diff ₹{diff:.2f}. "
                                "Verify extraction against the original invoice.",
                                {"line_sum": line_sum, "expected": expected_subtotal, "diff": diff})


class GSTINFormatValidator(InvoiceValidator):
    """Vendor GSTIN must match 15-char GST format."""
    code = "INVALID_GSTIN_FORMAT"

    def validate(self, draft, invoice, db) -> ValidationResult:
        from app.utils.gstin_utils import validate_gstin_format
        gstin = (getattr(invoice, "gst_number", None) or "").strip()
        if not gstin:
            # Blank GSTIN is handled by RCMValidator — not a format error
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No GSTIN — RCM check handles this")
        if validate_gstin_format(gstin):
            return ValidationResult(self.code, True, Severity.HARD_BLOCK,
                                    f"GSTIN {gstin} format valid (live verification pending GSTN API)")
        return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                f"GSTIN '{gstin}' is not a valid 15-character GST number. "
                                "Correct before pushing — ITC will be inadmissible.",
                                {"gstin": gstin})


class RCMValidator(InvoiceValidator):
    """Blank vendor GSTIN = unregistered vendor = RCM self-assessment required (S.9(4))."""
    code = "RCM_SELF_ASSESSMENT_REQUIRED"
    severity = Severity.HARD_BLOCK

    def validate(self, draft, invoice, db) -> ValidationResult:
        gstin = (getattr(invoice, "gst_number", None) or "").strip()
        if gstin:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK,
                                    "Vendor GSTIN present — S.9(4) RCM not applicable")
        return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                "Vendor GSTIN is missing. If this is an unregistered dealer, "
                                "Reverse Charge Mechanism (GST S.9(4)) applies — you must self-assess "
                                "and pay GST. Post this bill only after confirming RCM applicability.",
                                {"gstin": gstin})


class CompositionVendorValidator(InvoiceValidator):
    """Composition scheme vendors cannot charge GST — ITC is ineligible (Rule 42, S.17(5)).

    NON-OVERRIDABLE: there is no legitimate reason to push such a bill claiming ITC.
    Override capability is intentionally removed — this block cannot be bypassed via
    override_reason_code.
    """
    code = "COMPOSITION_VENDOR_ITC_INELIGIBLE"
    non_overridable = True  # Absolute hard stop — composition ITC is never valid

    def validate(self, draft, invoice, db) -> ValidationResult:
        from app.db.repository import VendorMappingRepository
        repo = VendorMappingRepository(db)
        mapping = repo.get_by_alias(draft.vendor_name or "", platform=draft.push_to or "zoho")
        if mapping and getattr(mapping, "is_composition_vendor", False):
            return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                    f"'{draft.vendor_name}' is a Composition Scheme vendor. "
                                    "ITC is NOT admissible (Rule 42, S.17(5) CGST Act). "
                                    "Use a non-ITC expense account and do not claim tax credit.",
                                    {"vendor": draft.vendor_name})
        return ValidationResult(self.code, True, Severity.HARD_BLOCK, "Not a composition vendor")


class DuplicateBillValidator(InvoiceValidator):
    """Detect probable duplicates.

    Primary check (HARD_BLOCK): same vendor + invoice_number already PUSHED.
    This catches re-submissions with a corrected date.

    Fallback check (HARD_BLOCK): same vendor + invoice_date + total_amount already PUSHED,
    used when invoice_number is blank (e.g., unstructured invoices).
    """
    code = "PROBABLE_DUPLICATE"

    def validate(self, draft, invoice, db) -> ValidationResult:
        from sqlalchemy import text

        invoice_number = (draft.invoice_number or "").strip()
        vendor_name = draft.vendor_name
        company_id = draft.company_id
        self_id = draft.id

        # ── Primary: match by invoice_number (strongest signal) ────────────
        if invoice_number:
            rows = db.execute(text("""
                SELECT id, invoice_number, pushed_at FROM invoice_drafts
                WHERE company_id = :cid
                  AND vendor_name = :vendor
                  AND invoice_number = :inv_num
                  AND status = 'PUSHED'
                  AND id != :self_id
            """), {
                "cid": company_id,
                "vendor": vendor_name,
                "inv_num": invoice_number,
                "self_id": self_id,
            }).fetchall()

            if rows:
                dup = rows[0]
                return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                        f"Invoice number '{invoice_number}' from this vendor was already pushed "
                                        f"(draft #{dup.id}). If this is a corrected re-issue, update the invoice "
                                        "number on the original before pushing this one.",
                                        {"duplicate_draft_id": dup.id, "duplicate_invoice": dup.invoice_number})
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No duplicates found (by invoice number)")

        # ── Fallback: match by date + amount when invoice_number is blank ──
        # Use a tolerance band instead of exact equality to handle float representation drift.
        amt = float(draft.total_amount or 0)
        rows = db.execute(text("""
            SELECT id, invoice_number, pushed_at FROM invoice_drafts
            WHERE company_id = :cid
              AND vendor_name = :vendor
              AND invoice_date = :date
              AND total_amount BETWEEN :amt - 0.01 AND :amt + 0.01
              AND status = 'PUSHED'
              AND id != :self_id
        """), {
            "cid": company_id,
            "vendor": vendor_name,
            "date": draft.invoice_date,
            "amt": amt,
            "self_id": self_id,
        }).fetchall()

        if not rows:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No duplicates found")
        dup = rows[0]
        return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                f"A bill with the same vendor, date and amount was already pushed "
                                f"(draft #{dup.id}, invoice {dup.invoice_number}). "
                                "Confirm this is a different invoice before pushing.",
                                {"duplicate_draft_id": dup.id, "duplicate_invoice": dup.invoice_number})


class GSTRoutingValidator(InvoiceValidator):
    """org_state_code must be configured before push — prevents silent wrong-tax-type booking.

    Without org_state_code, the system cannot deterministically route IGST vs CGST+SGST.
    Defaulting to intra-state and relying on Zoho error retry is unreliable — Zoho does not
    always return an error for wrong tax type, leading to silently misboooked bills.
    """
    code = "GST_ROUTING_UNCONFIGURED"

    def validate(self, draft, invoice, db) -> ValidationResult:
        if draft.push_to != "zoho":
            return ValidationResult(self.code, True, Severity.HARD_BLOCK,
                                    f"GST routing check not applicable for platform '{draft.push_to}'")

        from app.platforms.base import get_billing_platform
        try:
            platform = get_billing_platform(db, "zoho")
            org_state_code = (platform.config.get("org_state_code") or "").strip()
        except Exception:
            org_state_code = ""

        if not org_state_code:
            return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                    "Organisation State Code is not configured in Zoho integration settings. "
                                    "Cannot determine IGST vs CGST+SGST — go to Integrations → Zoho Books → "
                                    "set Organisation State Code before pushing any bill.",
                                    {"hint": "E.g. 29 = Karnataka, 33 = Tamil Nadu, 27 = Maharashtra"})

        return ValidationResult(self.code, True, Severity.HARD_BLOCK,
                                f"org_state_code configured: {org_state_code}")


class ITCTimeLimitValidator(InvoiceValidator):
    """S.16(4) CGST Act — ITC cannot be claimed after 30 November of the year following the invoice FY.

    Example: Invoice from FY 2023-24 (Apr 2023 – Mar 2024) → ITC cutoff = 30 Nov 2024.
    After that date, the ITC claim is time-barred regardless of invoice validity.
    """
    code = "ITC_TIME_LIMIT_EXCEEDED"

    def validate(self, draft, invoice, db) -> ValidationResult:
        invoice_date_str = (draft.invoice_date or "").strip()
        if not invoice_date_str:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No invoice date — skipped")

        inv_dt = self._parse_date(invoice_date_str)
        if not inv_dt:
            return ValidationResult(self.code, True, Severity.WARNING,
                                    f"ITC cutoff could not be verified — date format '{invoice_date_str}' not recognized. "
                                    "Manually confirm this invoice is within the ITC time limit before pushing.",
                                    {"invoice_date": invoice_date_str})

        today = date.today()
        # Indian FY runs Apr–Mar; determine the FY end year
        inv_fy_end_year = inv_dt.year if inv_dt.month >= 4 else inv_dt.year - 1
        cutoff = date(inv_fy_end_year + 1, 11, 30)  # 30 Nov of following year

        if today > cutoff:
            return ValidationResult(
                self.code, False, Severity.HARD_BLOCK,
                f"Invoice date {invoice_date_str} falls in FY {inv_fy_end_year}–{inv_fy_end_year + 1}. "
                f"ITC cutoff under S.16(4) CGST Act was {cutoff}. "
                "This ITC claim is time-barred — book to an expense account, do not claim tax credit.",
                {"invoice_date": invoice_date_str, "cutoff": str(cutoff),
                 "fy": f"{inv_fy_end_year}-{inv_fy_end_year + 1}"},
            )

        # Warning: within 60 days of cutoff
        if today > cutoff - timedelta(days=60):
            days_left = (cutoff - today).days
            return ValidationResult(
                self.code, True, Severity.WARNING,
                f"ITC time-limit warning: cutoff for this invoice is {cutoff} ({days_left} days remaining). "
                "Ensure this bill is included in your GSTR-3B before the deadline.",
                {"cutoff": str(cutoff), "days_left": days_left},
            )

        return ValidationResult(self.code, True, Severity.HARD_BLOCK,
                                f"Within ITC time limit (cutoff {cutoff})")

    @staticmethod
    def _parse_date(date_str: str):
        """Try common date formats. Returns date or None."""
        from datetime import datetime as _dt
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                return _dt.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        return None


def build_pre_push_pipeline():
    """Return the standard pre-push validation pipeline.

    Order matters:
    1. CompositionVendorValidator first — non-overridable, cheapest DB check
    2. GSTINFormatValidator / RCMValidator — GSTIN surface checks
    3. GSTRoutingValidator — config check before any push attempt
    4. ITCTimeLimitValidator — S.16(4) date check
    5. AmountReconciliationValidator — arithmetic integrity
    6. DuplicateBillValidator — last (most expensive query)
    """
    from app.services.validation.base import ValidationPipeline
    return ValidationPipeline([
        CompositionVendorValidator(),
        GSTINFormatValidator(),
        RCMValidator(),
        GSTRoutingValidator(),
        ITCTimeLimitValidator(),
        AmountReconciliationValidator(),
        DuplicateBillValidator(),
    ])
