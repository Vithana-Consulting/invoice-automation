"""Invoice parsing orchestration with pipeline validation gates.

Pipeline:
  1. Preflight check (company GST/PAN configured?)
  2. Parse document (OCR/LLM)
  3. Validate result (invoice_number mandatory, GST/PAN match)
  4. Save or fail with detailed errors/warnings
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import ParsingError
from app.db.repository import AuditLogRepository, InvoiceRepository
from app.parsers import get_parser
from app.services.pipeline import preflight_check, validate_parsed_invoice

logger = logging.getLogger(__name__)


class InvoiceService:
    def __init__(self, db: Session):
        self.db = db
        self.invoice_repo = InvoiceRepository(db)
        self.audit_repo = AuditLogRepository(db)

    def run_preflight(self) -> dict:
        """Run preflight checks before any parsing. Returns result dict.

        Call this before ingestion to verify company is ready.
        """
        result = preflight_check(self.db)
        return result.to_dict()

    def parse_invoice(self, invoice_id: int) -> bool:
        """Parse an invoice through the full validation pipeline.

        Pipeline:
          1. Preflight → company GST/PAN configured?
          2. Parse → OCR/LLM extraction
          3. Validate → invoice_number mandatory, GST/PAN match

        Returns True if parsing succeeded (even with warnings).
        Returns False if any gate fails.
        """
        # AI_RECOMMENDATION : the parsing logic is completely wrong? the sender and the vendor both(from and to) both can have gst's we have the company's name in repo/session and it is an invoice so, the from is an vendor and the to is the company. so we need to validate the user in the to and verify for gst /pan
        # AI_RECOMMENDATION : every invoice should have an mandatory BILL NUMBER and INVOICE DATE . Due date is optional, but parse it and save it as well

        record = self.invoice_repo.get_by_id(invoice_id)
        if not record:
            logger.error("Invoice %d not found", invoice_id)
            return False

        # ─── Gate 1: Preflight ─────────────────────────────────────
        preflight = preflight_check(self.db)
        if not preflight.success:
            error_msg = "; ".join(e["message"] for e in preflight.errors)
            self.invoice_repo.update_parsing_failed(invoice_id, error_msg)
            self.audit_repo.log(
                entity_type="invoice", entity_id=invoice_id, action="parsed",
                status="failure", error=f"Preflight failed: {error_msg}",
                details={"stage": "preflight", "errors": preflight.errors},
            )
            logger.warning("Invoice %d: preflight failed — %s", invoice_id, error_msg)
            return False

        # ─── Gate 2: Parse ─────────────────────────────────────────
        parser = get_parser()
        logger.info("Parsing invoice %d (%s) with %s", invoice_id, record.file_name, settings.PARSER_MODE)

        try:
            invoice = parser.parse(record.file_path, record.file_type or "pdf")
        except (ParsingError, Exception) as e:
            self.invoice_repo.update_parsing_failed(invoice_id, str(e))
            self.audit_repo.log(
                entity_type="invoice", entity_id=invoice_id, action="parsed",
                status="failure", error=str(e),
                details={"stage": "parse"},
            )
            logger.error("Invoice %d: parse failed — %s", invoice_id, e)
            return False

        # ─── Gate 3: Validate ──────────────────────────────────────
        validation = validate_parsed_invoice(invoice, self.db)
        all_issues = validation.errors + validation.warnings

        if not validation.success:
            # Fatal validation errors (e.g., missing invoice number)
            error_msg = "; ".join(e["message"] for e in validation.errors)
            # Still save parsed data so user can see what was extracted
            self.invoice_repo.update_parsed(invoice_id, invoice, settings.PARSER_MODE)
            self.invoice_repo._update(
                invoice_id,
                parsing_status="FAILED",
                validation_errors=json.dumps(all_issues),
            )
            self.audit_repo.log(
                entity_type="invoice", entity_id=invoice_id, action="parsed",
                status="failure", error=error_msg,
                details={
                    "stage": "validate",
                    "vendor_name": invoice.vendor_name,
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                },
            )
            logger.warning("Invoice %d: validation failed — %s", invoice_id, error_msg)
            return False

        # ─── Success (possibly with warnings) ──────────────────────
        has_warnings = bool(validation.warnings)
        self.invoice_repo.update_parsed(invoice_id, invoice, settings.PARSER_MODE)
        if has_warnings:
            self.invoice_repo._update(
                invoice_id,
                parsing_status="WARNING",
                validation_errors=json.dumps(all_issues),
            )

        self.audit_repo.log(
            entity_type="invoice", entity_id=invoice_id, action="parsed",
            status="warning" if has_warnings else "success",
            details={
                "parser_mode": settings.PARSER_MODE,
                "invoice_number": invoice.invoice_number,
                "vendor_name": invoice.vendor_name,
                "total_amount": invoice.total_amount,
                "warnings": validation.warnings if has_warnings else None,
            },
        )

        if has_warnings:
            logger.info("Invoice %d: parsed with %d warning(s)", invoice_id, len(validation.warnings))

        return True
