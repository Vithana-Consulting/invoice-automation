from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.platforms.base import InvoiceSource, register_source
from app.platforms.stripe.client import StripeClient

logger = logging.getLogger(__name__)


@register_source
class StripeSource(InvoiceSource):
    platform_key = "stripe"
    display_name = "Stripe"
    description = "Pull invoices from Stripe"
    category = "source"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client = StripeClient(api_key=config.get("api_key", ""))

    def test_connection(self) -> Dict[str, Any]:
        try:
            balance = self.client.get_balance()
            currency = balance.get("available", [{}])[0].get("currency", "?").upper()
            return {"healthy": True, "message": f"Connected to Stripe (currency: {currency})"}
        except Exception as e:
            return {"healthy": False, "message": str(e)}

    def fetch_invoices(self, db: Session, since: Optional[datetime] = None) -> Dict[str, Any]:
        """Pull invoices from Stripe and create InvoiceRecords + drafts."""
        from app.db.repository import InvoiceRepository
        from app.models.db_models import InvoiceRecord
        from app.services.draft_service import DraftService

        created_gte = int(since.timestamp()) if since else None
        result = self.client.list_invoices(limit=100, created_gte=created_gte)
        invoices = result.get("data", [])

        invoice_repo = InvoiceRepository(db)
        draft_service = DraftService(db)
        stats = {"total_found": len(invoices), "new": 0, "drafts_created": 0, "skipped": 0}

        for inv in invoices:
            source_ref = inv.get("id", "")
            # Skip if already ingested (check by source_ref)
            existing = db.query(InvoiceRecord).filter(InvoiceRecord.source_ref == source_ref).first()
            if existing:
                stats["skipped"] += 1
                continue

            record = InvoiceRecord(
                file_path="",
                file_name=f"stripe_{source_ref}",
                file_type="stripe_api",
                source="stripe",
                source_ref=source_ref,
                invoice_number=inv.get("number", ""),
                vendor_name=inv.get("customer_name") or inv.get("customer_email", ""),
                total_amount=inv.get("total", 0) / 100,  # Stripe amounts are in cents
                tax_amount=(inv.get("tax") or 0) / 100,
                currency=(inv.get("currency") or "usd").upper(),
                invoice_date=datetime.fromtimestamp(inv["created"]).strftime("%Y-%m-%d") if inv.get("created") else None,
                due_date=datetime.fromtimestamp(inv["due_date"]).strftime("%Y-%m-%d") if inv.get("due_date") else None,
                parsing_status="PARSED",
            )
            record = invoice_repo.create(record)
            stats["new"] += 1

            draft = draft_service.create_draft_from_invoice(record.id, source="stripe")
            if draft:
                stats["drafts_created"] += 1

        return stats

    @classmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        return [
            {"key": "api_key", "label": "Secret API Key (sk_...)", "type": "password", "required": True},
        ]
