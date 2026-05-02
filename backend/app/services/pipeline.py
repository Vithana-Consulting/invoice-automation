"""Invoice processing pipeline with validation gates.

Pipeline stages:
  1. PRE-FLIGHT  → Validate company config (GST/PAN set, Gmail working)
  2. INGEST      → Pull emails from Gmail
  3. PARSE       → OCR/LLM parse each invoice
  4. VALIDATE    → Check invoice_number (mandatory), GST/PAN match
  5. DRAFT       → Create draft for review

Each stage validates before proceeding. Failures are collected, not thrown.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.db_models import Company
from app.tenant.context import TenantContext

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a pipeline run with stage-level tracking."""
    success: bool = True
    stage: str = ""
    errors: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def add_error(self, code: str, message: str):
        self.errors.append({"code": code, "message": message})
        self.success = False

    def add_warning(self, code: str, message: str):
        self.warnings.append({"code": code, "message": message})

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stage": self.stage,
            "errors": self.errors,
            "warnings": self.warnings,
            "data": self.data,
        }


def preflight_check(db: Session) -> PipelineResult:
    """Gate 1: Validate company config before any processing.

    Checks:
      - Company GST or PAN is configured (at least one required)
      - Gmail integration exists and has credentials
    """
    result = PipelineResult(stage="preflight")

    company_id = TenantContext.get_optional()
    if not company_id:
        result.add_error("NO_TENANT", "No company context. Login required.")
        return result

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        result.add_error("COMPANY_NOT_FOUND", "Company not found.")
        return result

    # Block parsing if GST/PAN not configured
    if not company.gst_number and not company.pan_number:
        result.add_error(
            "MISSING_COMPANY_IDENTITY",
            "Company GST or PAN number not configured. "
            "Configure in Settings → Company before processing invoices.",
        )
        return result

    # Check Gmail integration
    from app.db.repository import IntegrationRepository
    int_repo = IntegrationRepository(db)
    gmail = int_repo.get_by_platform("gmail")
    if not gmail:
        result.add_warning("GMAIL_NOT_CONFIGURED", "Gmail integration not configured.")
    else:
        from app.platforms.base import decrypt_config
        config = decrypt_config(gmail.config_encrypted)
        if not config.get("token_json"):
            result.add_warning("GMAIL_NO_TOKEN", "Gmail not authorized. Authorize in Settings → Gmail API.")

    result.data = {
        "company": company.name,
        "gst_configured": bool(company.gst_number),
        "pan_configured": bool(company.pan_number),
    }

    return result


def validate_parsed_invoice(invoice, db: Session) -> PipelineResult:
    """Gate 3: Validate parsed invoice data.

    Checks:
      - invoice_number is MANDATORY (error)
      - invoice_date is MANDATORY (error)
      - buyer_gst_number matches company GSTIN (warning) — buyer is our company
      - buyer_pan_number matches company PAN (warning) — buyer is our company
    """
    result = PipelineResult(stage="validate")

    # Mandatory: invoice number
    if not invoice.invoice_number or not invoice.invoice_number.strip():
        result.add_error(
            "MISSING_INVOICE_NUMBER",
            "No invoice number found in the document. This field is required.",
        )

    # Mandatory: invoice date
    if not invoice.date or not str(invoice.date).strip():
        result.add_error(
            "MISSING_INVOICE_DATE",
            "No invoice date found in the document. This field is required.",
        )

    # Buyer GST/PAN validation — invoices are inbound: vendor → our company.
    # We validate the BUYER fields (buyer_gst_number, buyer_pan_number) against
    # the company's registered GST/PAN. The vendor's GST (gst_number) is informational.
    company_id = TenantContext.get_optional()
    if company_id:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            # Buyer GST check
            if not invoice.buyer_gst_number:
                result.add_warning("MISSING_BUYER_GST", "Buyer GSTIN not found in invoice.")
            elif company.gst_number and invoice.buyer_gst_number != company.gst_number:
                result.add_warning(
                    "GST_MISMATCH",
                    f"Buyer GSTIN on invoice ({invoice.buyer_gst_number}) does not match "
                    f"company GSTIN ({company.gst_number}).",
                )

            # Buyer PAN check
            if not invoice.buyer_pan_number:
                result.add_warning("MISSING_BUYER_PAN", "Buyer PAN not found in invoice.")
            elif company.pan_number and invoice.buyer_pan_number != company.pan_number:
                result.add_warning(
                    "PAN_MISMATCH",
                    f"Buyer PAN on invoice ({invoice.buyer_pan_number}) does not match "
                    f"company PAN ({company.pan_number}).",
                )

    return result
