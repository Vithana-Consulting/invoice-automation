from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.platforms.base import InvoiceSource, register_source
from app.platforms.chargebee.client import ChargebeeClient

logger = logging.getLogger(__name__)


@register_source
class ChargebeeSource(InvoiceSource):
    platform_key = "chargebee"
    display_name = "Chargebee"
    description = "Pull invoices from Chargebee"
    category = "source"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client = ChargebeeClient(
            site=config.get("site", ""),
            api_key=config.get("api_key", ""),
        )

    def test_connection(self) -> Dict[str, Any]:
        try:
            result = self.client.list_invoices(limit=1)
            return {"healthy": True, "message": "Connected to Chargebee"}
        except Exception as e:
            return {"healthy": False, "message": str(e)}

    def fetch_invoices(self, db: Session, since: Optional[datetime] = None) -> Dict[str, Any]:
        from app.db.repository import InvoiceRepository
        from app.models.db_models import InvoiceRecord
        from app.services.draft_service import DraftService

        updated_after = int(since.timestamp()) if since else None
        result = self.client.list_invoices(limit=100, updated_after=updated_after)
        entries = result.get("list", [])

        invoice_repo = InvoiceRepository(db)
        draft_service = DraftService(db)
        stats = {"total_found": len(entries), "new": 0, "drafts_created": 0, "skipped": 0}

        for entry in entries:
            inv = entry.get("invoice", {})
            source_ref = inv.get("id", "")
            existing = db.query(InvoiceRecord).filter(InvoiceRecord.source_ref == source_ref).first()
            if existing:
                stats["skipped"] += 1
                continue

            record = InvoiceRecord(
                file_path="",
                file_name=f"chargebee_{source_ref}",
                file_type="chargebee_api",
                source="chargebee",
                source_ref=source_ref,
                invoice_number=inv.get("id", ""),
                vendor_name=inv.get("customer_id", ""),
                total_amount=(inv.get("total") or 0) / 100,
                tax_amount=(inv.get("tax") or 0) / 100,
                currency=(inv.get("currency_code") or "USD").upper(),
                invoice_date=datetime.fromtimestamp(inv["date"]).strftime("%Y-%m-%d") if inv.get("date") else None,
                due_date=datetime.fromtimestamp(inv["due_date"]).strftime("%Y-%m-%d") if inv.get("due_date") else None,
                parsing_status="PARSED",
            )
            record = invoice_repo.create(record)
            stats["new"] += 1

            draft = draft_service.create_draft_from_invoice(record.id, source="chargebee")
            if draft:
                stats["drafts_created"] += 1

        return stats

    @classmethod
    def get_config_fields(cls) -> List[Dict[str, Any]]:
        return [
            {"key": "site", "label": "Chargebee Site Name (e.g. mycompany)", "type": "text", "required": True},
            {"key": "api_key", "label": "API Key", "type": "password", "required": True},
        ]
