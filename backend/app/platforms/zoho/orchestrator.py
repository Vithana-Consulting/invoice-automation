from __future__ import annotations

import logging
from typing import List

from sqlalchemy.orm import Session

from app.core.exceptions import ZohoError
from app.db.repository import AuditLogRepository, InvoiceRepository
from app.platforms.base import get_billing_platform
from app.platforms.zoho.mappers import invoice_to_zoho_bill

logger = logging.getLogger(__name__)


class ZohoService:
    """Orchestrates pushing invoices to Zoho Books as bills.

    Credentials loaded from integrations table (configured via UI).
    Uses the platform registry pattern.
    """

    def __init__(self, db: Session):
        self.db = db
        self.invoice_repo = InvoiceRepository(db)
        self.audit_repo = AuditLogRepository(db)
        self._platform = None

    @property
    def platform(self):
        if not self._platform:
            self._platform = get_billing_platform(self.db, "zoho")
        return self._platform

    def push_invoice(self, invoice_id: int) -> dict:
        record = self.invoice_repo.get_by_id(invoice_id)
        if not record:
            raise ZohoError(f"Invoice {invoice_id} not found")
        if record.parsing_status != "PARSED":
            raise ZohoError(f"Invoice {invoice_id} not parsed (status: {record.parsing_status})")

        vendor_name = record.vendor_name or "Unknown Vendor"
        try:
            vendor_id = self.platform.find_vendor(vendor_name)
            if not vendor_id:
                vendor_id = self.platform.create_vendor(vendor_name)
        except Exception as e:
            self.invoice_repo.update_zoho_status(invoice_id, "FAILED", error=f"Vendor lookup failed: {e}")
            raise

        payload = invoice_to_zoho_bill(record, vendor_id, self.platform.client.default_account_id)

        try:
            result = self.platform.client.create_bill(payload)
            bill = result.get("bill", {})
            bill_id = bill.get("bill_id", "")
            self.invoice_repo.update_zoho_status(invoice_id, "PUSHED", bill_id=bill_id, vendor_id=vendor_id)
            self.audit_repo.log(
                entity_type="invoice", entity_id=invoice_id, action="zoho_pushed",
                details={"zoho_bill_id": bill_id, "zoho_vendor_id": vendor_id},
            )
            return {"invoice_id": invoice_id, "zoho_bill_id": bill_id, "zoho_vendor_id": vendor_id, "success": True}
        except Exception as e:
            self.invoice_repo.update_zoho_status(invoice_id, "FAILED", error=str(e))
            self.audit_repo.log(
                entity_type="invoice", entity_id=invoice_id, action="zoho_pushed",
                status="failure", error=str(e),
            )
            raise

    def push_all_unpushed(self) -> List[dict]:
        unpushed = self.invoice_repo.list_unpushed()
        results = []
        for record in unpushed:
            try:
                result = self.push_invoice(record.id)
                results.append(result)
            except Exception as e:
                results.append({"invoice_id": record.id, "success": False, "error": str(e)})
        return results
