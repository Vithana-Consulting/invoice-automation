from __future__ import annotations

import json
import logging
from datetime import datetime
from io import BytesIO
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.repository import (
    AuditLogRepository,
    ChartOfAccountRepository,
    DraftRepository,
    InvoiceRepository,
    RuleRepository,
    VendorMappingRepository,
)
from app.models.db_models import InvoiceDraft, InvoiceRecord
from app.rules.engine import apply_rules

logger = logging.getLogger(__name__)


class DraftService:
    """Manages the invoice draft lifecycle: create, review, approve, push."""

    def __init__(self, db: Session):
        self.db = db
        self.draft_repo = DraftRepository(db)
        self.invoice_repo = InvoiceRepository(db)
        self.mapping_repo = VendorMappingRepository(db)
        self.rule_repo = RuleRepository(db)
        self.audit_repo = AuditLogRepository(db)
        self.coa_repo = ChartOfAccountRepository(db)

    def create_draft_from_invoice(self, invoice_id: int, source: str = "gmail") -> Optional[InvoiceDraft]:
        """Create a draft from a parsed invoice, applying rules then vendor mapping.

        Order matters:
          1. Run rules first → determines push_to (which platform)
          2. Resolve vendor alias for that specific platform
        """
        invoice = self.invoice_repo.get_by_id(invoice_id)
        if not invoice or invoice.parsing_status not in ("PARSED", "WARNING"):
            return None

        existing = self.draft_repo.get_by_invoice_id(invoice_id)
        if existing:
            logger.info("Draft already exists for invoice %d", invoice_id)
            return existing

        vendor_name = invoice.vendor_name or ""

        # Step 1: Build invoice fields for rule evaluation (use raw vendor_name)
        invoice_fields = {
            "vendor_name": vendor_name,
            "resolved_vendor_name": vendor_name,  # not yet resolved
            "invoice_number": invoice.invoice_number or "",
            "total_amount": float(invoice.total_amount) if invoice.total_amount else 0,
            "tax_amount": float(invoice.tax_amount) if invoice.tax_amount else 0,
            "currency": invoice.currency or "INR",
            "source": source,
            "invoice_date": invoice.invoice_date or "",
            "gst_number": invoice.gst_number or "",
        }

        # Step 2: Apply rules → determines push_to platform
        active_rules = self.rule_repo.list_all(active_only=True)
        rule_dicts = [
            {
                "id": r.id, "name": r.name,
                "conditions_json": r.conditions_json,
                "action_type": r.action_type,
                "action_value": r.action_value,
            }
            for r in active_rules
        ]
        matched_rule = apply_rules(rule_dicts, invoice_fields)

        push_to = None
        push_to_rule_id = None
        if matched_rule:
            push_to = matched_rule["action_value"]
            push_to_rule_id = matched_rule["id"]

        # Step 3: Resolve vendor alias FOR the target platform
        resolved_vendor_name = vendor_name
        if push_to:
            mapping = self.mapping_repo.get_by_alias(vendor_name, platform=push_to)
        else:
            mapping = self.mapping_repo.get_by_alias(vendor_name)
        if mapping:
            resolved_vendor_name = mapping.canonical_name
            logger.info(
                "Vendor alias resolved: '%s' -> '%s' (platform=%s)",
                vendor_name, resolved_vendor_name, mapping.platform,
            )

        # Step 4: Determine invoice type (inbound/outbound) based on GST
        invoice_type = self._determine_invoice_type(invoice)

        # Step 5: Auto-assign GL account based on type + HSN
        account_id = self._assign_account(invoice, invoice_type)

        # Step 6: Create draft (carry validation warnings + tax breakup)
        validation_warnings = invoice.validation_errors if invoice.parsing_status == "WARNING" else None
        draft = self.draft_repo.create(
            invoice_id=invoice_id,
            vendor_name=vendor_name,
            resolved_vendor_name=resolved_vendor_name,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            total_amount=invoice.total_amount,
            tax_amount=invoice.tax_amount,
            currency=invoice.currency or "INR",
            line_items_json=invoice.line_items_json,
            source=source,
            push_to=push_to,
            push_to_rule_id=push_to_rule_id,
            status="PENDING_REVIEW",
            validation_warnings=validation_warnings,
            tax_breakup_json=invoice.tax_breakup_json,
            invoice_type=invoice_type,
            account_id=account_id,
        )

        self.audit_repo.log(
            entity_type="draft",
            entity_id=draft.id,
            action="draft_created",
            details={
                "invoice_id": invoice_id,
                "vendor_name": vendor_name,
                "resolved_vendor_name": resolved_vendor_name,
                "push_to": push_to,
                "rule_matched": matched_rule["name"] if matched_rule else None,
            },
        )

        return draft

    def refresh_draft_from_invoice(self, draft_id: int) -> Optional[InvoiceDraft]:
        """Re-sync a draft's extracted fields from its invoice record after a reparse.

        Updates: vendor_name, invoice_number, invoice_date, due_date, total_amount,
                 tax_amount, line_items_json, tax_breakup_json, validation_warnings.
        Preserves: status, push_to, resolved_vendor_name, account_id, push_error.
        Resets: validation_errors (cleared so next push re-runs pipeline fresh).
        """
        draft = self.draft_repo.get_by_id(draft_id)
        if not draft:
            return None

        invoice = self.invoice_repo.get_by_id(draft.invoice_id)
        if not invoice or invoice.parsing_status not in ("PARSED", "WARNING"):
            return None

        validation_warnings = invoice.validation_errors if invoice.parsing_status == "WARNING" else None
        invoice_type = self._determine_invoice_type(invoice)
        account_id = self._assign_account(invoice, invoice_type)

        updated = self.draft_repo.update(
            draft_id,
            vendor_name=invoice.vendor_name or draft.vendor_name,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            total_amount=invoice.total_amount,
            tax_amount=invoice.tax_amount,
            line_items_json=invoice.line_items_json,
            tax_breakup_json=invoice.tax_breakup_json,
            invoice_type=invoice_type,
            account_id=account_id,
            validation_warnings=validation_warnings,
            validation_errors=None,   # cleared — next push re-runs pipeline
            push_error=None,
        )

        self.audit_repo.log(
            entity_type="draft",
            entity_id=draft_id,
            action="draft_refreshed_from_reparse",
            details={"invoice_id": invoice.id, "new_total": float(invoice.total_amount or 0)},
        )

        return updated

    def create_drafts_for_parsed_invoices(self, source: str = "gmail") -> List[InvoiceDraft]:
        """Create drafts for all parsed invoices (including WARNING) that don't have drafts yet."""
        parsed = self.invoice_repo.list_all(parsing_status="PARSED")
        warned = self.invoice_repo.list_all(parsing_status="WARNING")
        drafts = []
        for invoice in parsed + warned:
            draft = self.create_draft_from_invoice(invoice.id, source=source)
            if draft:
                drafts.append(draft)
        return drafts

    def _determine_invoice_type(self, invoice: InvoiceRecord) -> str:
        """Determine if invoice is INBOUND (purchase) or OUTBOUND (sale).

        Logic: if seller GST matches company GST → OUTBOUND (we issued it)
               if buyer GST matches company GST → INBOUND (we received it)
               default → INBOUND (most invoices are received purchases)
        """
        from app.models.db_models import Company
        from app.tenant.context import TenantContext

        company_id = TenantContext.get_optional()
        if not company_id:
            return "INBOUND"

        company = self.db.query(Company).filter(Company.id == company_id).first()
        if not company or not company.gst_number:
            return "INBOUND"

        seller_gst = invoice.gst_number or ""
        buyer_gst = invoice.buyer_gst_number or ""

        if seller_gst and seller_gst.upper() == company.gst_number.upper():
            return "OUTBOUND"
        if buyer_gst and buyer_gst.upper() == company.gst_number.upper():
            return "INBOUND"
        return "INBOUND"

    def _assign_account(self, invoice: InvoiceRecord, invoice_type: str) -> Optional[int]:
        """Auto-assign GL account based on invoice type, HSN codes, and push platform.

        Priority:
          1. HSN-based match on any synced platform account
          2. Default account for sub_type PURCHASE or SALE
        """
        # Try HSN-based assignment from first line item
        if invoice.line_items_json:
            try:
                items = json.loads(invoice.line_items_json)
                for item in items:
                    hsn = item.get("hsn_or_sac")
                    if hsn:
                        acc = self.coa_repo.get_by_hsn(hsn)
                        if acc:
                            return acc.id
            except (json.JSONDecodeError, TypeError):
                pass

        # Fall back to default account for type (any platform)
        sub_type = "PURCHASE" if invoice_type == "INBOUND" else "SALE"
        default = self.coa_repo.get_default(sub_type)
        return default.id if default else None

    def approve_draft(self, draft_id: int, user_id: int = None) -> Optional[InvoiceDraft]:
        draft = self.draft_repo.get_by_id(draft_id)
        if not draft or draft.status not in ("PENDING_REVIEW", "PENDING_VENDOR"):
            return None

        # Check vendor mapping if push_to is set
        if draft.push_to and draft.vendor_name:
            mapping = self.mapping_repo.get_by_alias(draft.vendor_name, platform=draft.push_to)
            if not mapping:
                # No vendor mapping — park in PENDING_VENDOR
                updated = self.draft_repo.update(
                    draft_id,
                    status="PENDING_VENDOR",
                    reviewed_by=user_id,
                    reviewed_at=datetime.utcnow(),
                )
                self.audit_repo.log(
                    entity_type="draft",
                    entity_id=draft_id,
                    action="pending_vendor",
                    details={
                        "vendor_name": draft.vendor_name,
                        "push_to": draft.push_to,
                        "reason": f"No vendor mapping for '{draft.vendor_name}' on {draft.push_to}",
                    },
                )
                return updated
            else:
                # Update resolved vendor name from mapping
                return self.draft_repo.update(
                    draft_id,
                    status="APPROVED",
                    resolved_vendor_name=mapping.canonical_name,
                    reviewed_by=user_id,
                    reviewed_at=datetime.utcnow(),
                )

        return self.draft_repo.update(
            draft_id,
            status="APPROVED",
            reviewed_by=user_id,
            reviewed_at=datetime.utcnow(),
        )

    def reject_draft(self, draft_id: int, user_id: int = None) -> Optional[InvoiceDraft]:
        draft = self.draft_repo.get_by_id(draft_id)
        if not draft or draft.status not in ("PENDING_REVIEW", "APPROVED"):
            return None
        return self.draft_repo.update(
            draft_id,
            status="REJECTED",
            reviewed_by=user_id,
            reviewed_at=datetime.utcnow(),
        )

    def resolve_pending_vendors(self, platform: str = None) -> List[dict]:
        """Check all PENDING_VENDOR drafts and transition to APPROVED if mapping now exists."""
        pending = self.draft_repo.list_all(status="PENDING_VENDOR", limit=500)
        results = []

        for draft in pending:
            if platform and draft.push_to != platform:
                continue
            if not draft.push_to or not draft.vendor_name:
                continue

            mapping = self.mapping_repo.get_by_alias(draft.vendor_name, platform=draft.push_to)
            if mapping:
                self.draft_repo.update(
                    draft.id,
                    status="APPROVED",
                    resolved_vendor_name=mapping.canonical_name,
                )
                self.audit_repo.log(
                    entity_type="draft",
                    entity_id=draft.id,
                    action="vendor_resolved",
                    details={
                        "vendor_name": draft.vendor_name,
                        "resolved_to": mapping.canonical_name,
                        "platform": draft.push_to,
                        "mapping_id": mapping.id,
                    },
                )
                results.append({
                    "draft_id": draft.id,
                    "vendor_name": draft.vendor_name,
                    "resolved_to": mapping.canonical_name,
                    "status": "APPROVED",
                })

        return results

    def bulk_approve(self, draft_ids: List[int], user_id: int = None) -> List[dict]:
        results = []
        for draft_id in draft_ids:
            draft = self.approve_draft(draft_id, user_id)
            results.append({
                "draft_id": draft_id,
                "success": draft is not None,
            })
        return results

    def export_to_excel(self, status: str = None, push_to: str = None, source: str = None) -> BytesIO:
        """Export drafts to Excel (.xlsx) format."""
        from openpyxl import Workbook

        drafts = self.draft_repo.list_all(status=status, push_to=push_to, source=source, limit=10000)

        wb = Workbook()
        ws = wb.active
        ws.title = "Invoice Drafts"

        headers = [
            "ID", "Invoice #", "Vendor Name", "Resolved Vendor", "Invoice Date",
            "Due Date", "Amount", "Tax", "CGST", "SGST", "IGST",
            "Currency", "Type", "GL Account", "Source", "Push To",
            "Status", "External Bill ID", "Created At",
        ]
        ws.append(headers)

        for draft in drafts:
            # Parse tax breakup
            cgst = sgst = igst = 0
            if draft.tax_breakup_json:
                try:
                    tb = json.loads(draft.tax_breakup_json)
                    cgst = tb.get("cgst_amount") or 0
                    sgst = tb.get("sgst_amount") or 0
                    igst = tb.get("igst_amount") or 0
                except (json.JSONDecodeError, TypeError):
                    pass

            ws.append([
                draft.id,
                draft.invoice_number or "",
                draft.vendor_name or "",
                draft.resolved_vendor_name or "",
                draft.invoice_date or "",
                draft.due_date or "",
                float(draft.total_amount) if draft.total_amount else 0,
                float(draft.tax_amount) if draft.tax_amount else 0,
                cgst, sgst, igst,
                draft.currency or "INR",
                draft.invoice_type or "",
                draft.account.name if draft.account else "",
                draft.source or "",
                draft.push_to or "",
                draft.status or "",
                draft.external_bill_id or "",
                str(draft.created_at) if draft.created_at else "",
            ])

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    def get_dashboard_summary(self) -> dict:
        """Get summary counts for the dashboard."""
        counts = self.draft_repo.count_by_status()
        total = sum(counts.values())
        return {
            "total": total,
            "pending_review": counts.get("PENDING_REVIEW", 0),
            "pending_vendor": counts.get("PENDING_VENDOR", 0),
            "approved": counts.get("APPROVED", 0),
            "pushed": counts.get("PUSHED", 0),
            "push_failed": counts.get("PUSH_FAILED", 0),
            "rejected": counts.get("REJECTED", 0),
        }
