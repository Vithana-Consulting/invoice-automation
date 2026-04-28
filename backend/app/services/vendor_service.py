from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import VendorLookupError
from app.db.repository import AuditLogRepository, VendorCacheRepository
from app.platforms.zoho.mappers import build_vendor_payload

logger = logging.getLogger(__name__)


class VendorService:
    """Find or create vendors in Zoho Books with local caching.

    Requires a pre-configured ZohoClient (credentials from DB, not env).
    """

    def __init__(self, db: Session, zoho_client=None):
        self.db = db
        self.cache_repo = VendorCacheRepository(db)
        self.audit_repo = AuditLogRepository(db)
        self.zoho_client = zoho_client

    def find_or_create(self, vendor_name: str, gst_number: str = None) -> str:
        if not vendor_name:
            raise VendorLookupError("Vendor name is required")
        if not self.zoho_client:
            raise VendorLookupError("Zoho client not configured. Set up Zoho integration first.")

        cached = self.cache_repo.get_by_name(vendor_name)
        if cached:
            logger.info("Vendor '%s' found in local cache: %s", vendor_name, cached.zoho_vendor_id)
            return cached.zoho_vendor_id

        try:
            contacts = self.zoho_client.list_contacts(contact_name=vendor_name)
            for contact in contacts:
                if contact.get("contact_name", "").lower() == vendor_name.lower():
                    vendor_id = contact["contact_id"]
                    self.cache_repo.create(vendor_name, vendor_id, gst_number)
                    return vendor_id
        except Exception as e:
            logger.warning("Zoho vendor search failed for '%s': %s", vendor_name, e)

        try:
            payload = build_vendor_payload(vendor_name, gst_number)
            result = self.zoho_client.create_contact(payload)
            contact = result.get("contact", {})
            vendor_id = contact.get("contact_id")
            if not vendor_id:
                raise VendorLookupError(f"Zoho create contact response missing contact_id: {result}")
            self.cache_repo.create(vendor_name, vendor_id, gst_number)
            self.audit_repo.log(
                entity_type="vendor", entity_id=0, action="vendor_created",
                details={"vendor_name": vendor_name, "zoho_vendor_id": vendor_id, "gst_number": gst_number},
            )
            return vendor_id
        except VendorLookupError:
            raise
        except Exception as e:
            raise VendorLookupError(f"Failed to create vendor '{vendor_name}' in Zoho: {e}")
