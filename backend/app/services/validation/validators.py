from __future__ import annotations
import json
from app.services.validation.base import InvoiceValidator, ValidationResult, Severity
from app.utils.gstin_utils import validate_gstin_format, extract_state_code


class AmountReconciliationValidator(InvoiceValidator):
    """Line-item subtotal must foot to invoice total_amount within tolerance."""
    code = "RECONCILIATION_FAILED"
    TOLERANCE = 1.0  # ₹1 rounding tolerance

    def validate(self, draft, invoice, db) -> ValidationResult:
        total = float(draft.total_amount or 0)
        tax   = float(draft.tax_amount or 0)
        if total == 0:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No total amount — skipped")

        items = []
        try:
            items = json.loads(invoice.line_items_json or "[]")
        except Exception:
            pass

        if not items:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No line items — skipped")

        line_sum = sum(float(i.get("amount", 0) or 0) for i in items)
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
    """Blank vendor GSTIN = unregistered vendor = RCM self-assessment required."""
    code = "RCM_SELF_ASSESSMENT_REQUIRED"
    severity = Severity.HARD_BLOCK

    def validate(self, draft, invoice, db) -> ValidationResult:
        gstin = (getattr(invoice, "gst_number", None) or "").strip()
        if gstin:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK,
                                    "Vendor GSTIN present — RCM not applicable")
        return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                "Vendor GSTIN is missing. If this is an unregistered dealer, "
                                "Reverse Charge Mechanism (GST S.9(4)) applies — you must self-assess "
                                "and pay GST. Post this bill only after confirming RCM applicability.",
                                {"gstin": gstin})


class CompositionVendorValidator(InvoiceValidator):
    """Composition scheme vendors cannot charge GST — ITC is ineligible."""
    code = "COMPOSITION_VENDOR_ITC_INELIGIBLE"

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
    """Detect probable duplicates: same vendor + invoice_date + total_amount already PUSHED."""
    code = "PROBABLE_DUPLICATE"

    def validate(self, draft, invoice, db) -> ValidationResult:
        from sqlalchemy import text
        rows = db.execute(text("""
            SELECT id, invoice_number, pushed_at FROM invoice_drafts
            WHERE company_id = :cid
              AND vendor_name = :vendor
              AND invoice_date = :date
              AND total_amount = :amt
              AND status = 'PUSHED'
              AND id != :self_id
        """), {
            "cid": draft.company_id,
            "vendor": draft.vendor_name,
            "date": draft.invoice_date,
            "amt": float(draft.total_amount or 0),
            "self_id": draft.id,
        }).fetchall()

        if not rows:
            return ValidationResult(self.code, True, Severity.HARD_BLOCK, "No duplicates found")
        dup = rows[0]
        return ValidationResult(self.code, False, Severity.HARD_BLOCK,
                                f"A bill with the same vendor, date and amount was already pushed "
                                f"(draft #{dup.id}, invoice {dup.invoice_number}). "
                                "Confirm this is a different invoice before pushing.",
                                {"duplicate_draft_id": dup.id, "duplicate_invoice": dup.invoice_number})


def build_pre_push_pipeline():
    """Return the standard pre-push validation pipeline."""
    from app.services.validation.base import ValidationPipeline
    return ValidationPipeline([
        GSTINFormatValidator(),
        RCMValidator(),
        CompositionVendorValidator(),
        AmountReconciliationValidator(),
        DuplicateBillValidator(),
    ])
