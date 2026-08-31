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
from app.db.repository import AuditLogRepository, ExtractionLogRepository, InvoiceRepository
from app.db.session import db_session
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

        Deliberately does NOT use self.db for gates 1/3 — a multi-second
        GPT-4o parse call sits between them, and holding the caller's pooled
        session open across it starves every other API sharing the pool
        (same failure mode fixed in adhoc_routes.py; see that file's
        module docstring). Each gate opens and closes its own short-lived
        session instead, so no connection is checked out during the parse.
        """
        from app.models.db_models import Company
        from app.tenant.context import TenantContext

        # ─── Gate 1: fetch + preflight (short session) ──────────────
        with db_session() as db:
            record = InvoiceRepository(db).get_by_id(invoice_id)
            if not record:
                logger.error("Invoice %d not found", invoice_id)
                return False

            preflight = preflight_check(db)
            if not preflight.success:
                error_msg = "; ".join(e["message"] for e in preflight.errors)
                InvoiceRepository(db).update_parsing_failed(invoice_id, error_msg)
                AuditLogRepository(db).log(
                    entity_type="invoice", entity_id=invoice_id, action="parsed",
                    status="failure", error=f"Preflight failed: {error_msg}",
                    details={"stage": "preflight", "errors": preflight.errors},
                )
                logger.warning("Invoice %d: preflight failed — %s", invoice_id, error_msg)
                return False

            file_path = record.file_path
            file_type = record.file_type or "pdf"
            file_name = record.file_name

            # Build buyer hint so the AI never mistakes our company for the vendor
            buyer_hint = None
            try:
                cid = TenantContext.get_optional()
                if cid:
                    company = db.query(Company).filter(Company.id == cid).first()
                    if company and (company.legal_name or company.gst_number or company.pan_number):
                        buyer_hint = {
                            "legal_name": company.legal_name or company.name,
                            "gst_number": company.gst_number,
                            "pan_number": company.pan_number,
                        }
            except Exception:
                pass  # best-effort — never block parsing

        # ─── Gate 2: Parse — NO db connection held across this ───────
        parser = get_parser()
        logger.info("Parsing invoice %d (%s) with %s", invoice_id, file_name, settings.PARSER_MODE)

        raw_parsed_data: dict = {}
        try:
            invoice = parser.parse(file_path, file_type, buyer_hint=buyer_hint)
            # Capture raw parsed data for ExtractionLog (best-effort)
            try:
                raw_parsed_data = invoice.model_dump()
            except Exception:
                pass
        except (ParsingError, Exception) as e:
            with db_session() as db:
                InvoiceRepository(db).update_parsing_failed(invoice_id, str(e))
                AuditLogRepository(db).log(
                    entity_type="invoice", entity_id=invoice_id, action="parsed",
                    status="failure", error=str(e),
                    details={"stage": "parse"},
                )
            logger.error("Invoice %d: parse failed — %s", invoice_id, e)
            return False

        # ─── Gate 3: Validate + save (short session) ─────────────────
        with db_session() as db:
            invoice_repo = InvoiceRepository(db)
            audit_repo = AuditLogRepository(db)

            validation = validate_parsed_invoice(invoice, db)
            all_issues = validation.errors + validation.warnings

            if not validation.success:
                # Fatal validation errors (e.g., missing invoice number)
                error_msg = "; ".join(e["message"] for e in validation.errors)
                # Still save parsed data so user can see what was extracted
                invoice_repo.update_parsed(invoice_id, invoice, settings.PARSER_MODE)
                invoice_repo._update(
                    invoice_id,
                    parsing_status="FAILED",
                    validation_errors=json.dumps(all_issues),
                )
                audit_repo.log(
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
            invoice_repo.update_parsed(invoice_id, invoice, settings.PARSER_MODE)

            # Store immutable extraction log (S.36 CGST Act — 72-month retention)
            try:
                ExtractionLogRepository(db).create(
                    invoice_id=invoice_id,
                    raw_llm_json=json.dumps(raw_parsed_data),
                    parser_mode=getattr(invoice, "parser_mode", None) or settings.PARSER_MODE,
                )
            except Exception as exc:
                logger.warning("Failed to store extraction log for invoice %d: %s", invoice_id, exc)

            if has_warnings:
                invoice_repo._update(
                    invoice_id,
                    parsing_status="WARNING",
                    validation_errors=json.dumps(all_issues),
                )

            audit_repo.log(
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
