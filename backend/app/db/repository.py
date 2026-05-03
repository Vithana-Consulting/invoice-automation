"""Repository layer — data access for all models.

Architecture:
  - Tenant-scoped repos extend TenantBaseRepository (auto-filters by company_id)
  - Global repos (UserRepository) access data across all companies
  - All query methods use _base_query() for automatic tenant isolation
  - All create methods use _stamp() or _create() to set company_id
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.db_models import (
    AuditLog,
    ChartOfAccount,
    Company,
    CompanyMember,
    ExtractionLog,
    InvoiceDraft,
    InvoiceRecord,
    Integration,
    LegacyAuditLog,
    PlatformVendor,
    ProcessedEmail,
    Rule,
    User,
    VendorCache,
    VendorMapping,
)
from app.tenant.repository import TenantBaseRepository

logger = logging.getLogger(__name__)


# ─── Global Repositories (no tenant filtering) ────────────────────────────


class UserRepository:
    """User management — global, not tenant-scoped."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def get_by_google_sub(self, google_sub: str) -> Optional[User]:
        return self.db.query(User).filter(User.google_sub == google_sub).first()

    def create_or_update(self, google_sub: str, email: str, name: str, picture_url: str) -> User:
        """Upsert user from Google OAuth. Returns the User record."""
        user = self.get_by_google_sub(google_sub)
        if user:
            user.email = email
            user.name = name
            user.picture_url = picture_url
            user.last_login_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(user)
            return user

        user = User(
            email=email,
            name=name,
            picture_url=picture_url,
            google_sub=google_sub,
            last_login_at=datetime.utcnow(),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user


# ─── Tenant-Scoped Repositories ───────────────────────────────────────────


class EmailRepository(TenantBaseRepository):
    """Processed email records from Gmail/other sources."""
    model = ProcessedEmail

    def exists(self, message_id: str) -> bool:
        return self._base_query().filter(ProcessedEmail.message_id == message_id).first() is not None

    def create(self, email: ProcessedEmail) -> ProcessedEmail:
        return self._create(email)

    def update_status(self, email_id: int, status: str, error: str = None):
        return self._update(email_id, status=status, error_message=error)

    def list_all(self, status: str = None, limit: int = 50, offset: int = 0) -> List[ProcessedEmail]:
        query = self._base_query()
        if status:
            query = query.filter(ProcessedEmail.status == status)
        return query.order_by(ProcessedEmail.fetched_at.desc()).offset(offset).limit(limit).all()


class InvoiceRepository(TenantBaseRepository):
    """Invoice records — raw files with parsed metadata."""
    model = InvoiceRecord

    def create(self, record: InvoiceRecord) -> InvoiceRecord:
        return self._create(record)

    def get_by_id(self, invoice_id: int) -> Optional[InvoiceRecord]:
        return self._get_by_id(invoice_id)

    def get_by_content_hash(self, content_hash: str) -> Optional[InvoiceRecord]:
        return self._base_query().filter(InvoiceRecord.content_hash == content_hash).first()

    def update_parsed(self, invoice_id: int, invoice, parser_mode: str):
        """Save parsed invoice data to the record."""
        updates = {
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
            "invoice_date": invoice.date,
            "due_date": invoice.due_date,
            "total_amount": invoice.total_amount,
            "tax_amount": invoice.tax_amount,
            "subtotal": invoice.subtotal,
            "gst_number": invoice.gst_number,
            "buyer_gst_number": invoice.buyer_gst_number,
            "pan_number": invoice.pan_number,
            "buyer_pan_number": invoice.buyer_pan_number,
            "vendor_address": invoice.vendor_address,
            "uan_number": invoice.uan_number,
            "currency": invoice.currency,
            "line_items_json": json.dumps([item.model_dump() for item in invoice.line_items]) if invoice.line_items else None,
            "tax_breakup_json": json.dumps(invoice.tax_breakup.model_dump()) if invoice.tax_breakup else None,
            "bank_details_json": json.dumps(invoice.bank_details.model_dump()) if invoice.bank_details else None,
            "raw_text": invoice.raw_text,
            "parser_mode": parser_mode,
            "parsing_status": "PARSED",
            "confidence_scores": json.dumps(invoice.confidence_scores) if invoice.confidence_scores else None,
            "place_of_supply": getattr(invoice, "place_of_supply", None),
        }
        return self._update(invoice_id, **updates)

    def update_parsing_failed(self, invoice_id: int, error: str):
        return self._update(invoice_id, parsing_status="FAILED", validation_errors=error)

    def list_all(self, parsing_status: str = None, limit: int = 50, offset: int = 0) -> List[InvoiceRecord]:
        query = self._base_query()
        if parsing_status:
            query = query.filter(InvoiceRecord.parsing_status == parsing_status)
        return query.order_by(InvoiceRecord.created_at.desc()).offset(offset).limit(limit).all()


class VendorCacheRepository(TenantBaseRepository):
    """Legacy vendor cache from Day2."""
    model = VendorCache

    def get_by_name(self, vendor_name: str) -> Optional[VendorCache]:
        return self._base_query().filter(VendorCache.vendor_name == vendor_name).first()

    def create(self, vendor_name: str, zoho_vendor_id: str = None, gst_number: str = None) -> VendorCache:
        record = VendorCache(vendor_name=vendor_name, zoho_vendor_id=zoho_vendor_id, gst_number=gst_number)
        return self._create(record)


class AuditLogRepository(TenantBaseRepository):
    """Audit trail for all significant actions (legacy table)."""
    model = LegacyAuditLog

    def log(self, entity_type: str, entity_id: int, action: str,
            details: dict = None, status: str = "success", error: str = None):
        """Create an audit log entry, scoped to the current tenant."""
        record = LegacyAuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            details=json.dumps(details) if details else None,
            status=status,
            error_message=error,
        )
        return self._create(record)

    def list_recent(self, limit: int = 20) -> List[LegacyAuditLog]:
        return self._base_query().order_by(LegacyAuditLog.created_at.desc()).limit(limit).all()


class VendorMappingRepository(TenantBaseRepository):
    """Maps invoice vendor names to platform-specific canonical names."""
    model = VendorMapping

    def get_by_id(self, mapping_id: int) -> Optional[VendorMapping]:
        return self._get_by_id(mapping_id)

    def get_by_alias(self, alias_name: str, platform: str = None) -> Optional[VendorMapping]:
        """Look up a vendor mapping by alias name.

        If platform is specified, tries exact platform match first,
        then falls back to any platform.
        """
        if platform:
            match = (
                self._base_query()
                .filter(VendorMapping.alias_name.ilike(alias_name))
                .filter(VendorMapping.platform == platform)
                .first()
            )
            if match:
                return match
        return self._base_query().filter(VendorMapping.alias_name.ilike(alias_name)).first()

    def get_exact(self, alias_name: str, platform: str) -> Optional[VendorMapping]:
        """Strict match on alias + platform (for duplicate checking)."""
        return (
            self._base_query()
            .filter(VendorMapping.alias_name.ilike(alias_name))
            .filter(VendorMapping.platform == platform)
            .first()
        )

    def create(self, alias_name: str, canonical_name: str, platform: str,
               platform_vendor_id: str = None, created_by: int = None) -> VendorMapping:
        record = VendorMapping(
            alias_name=alias_name,
            canonical_name=canonical_name,
            platform=platform,
            platform_vendor_id=platform_vendor_id,
            created_by=created_by,
        )
        return self._create(record)

    def update(self, mapping_id: int, **kwargs) -> Optional[VendorMapping]:
        return self._update(mapping_id, **kwargs)

    def delete(self, mapping_id: int) -> bool:
        return self._delete(mapping_id)

    def list_all(self, search: str = None, platform: str = None,
                 limit: int = 50, offset: int = 0) -> List[VendorMapping]:
        query = self._base_query()
        if search:
            query = query.filter(
                VendorMapping.alias_name.ilike(f"%{search}%")
                | VendorMapping.canonical_name.ilike(f"%{search}%")
            )
        if platform:
            query = query.filter(VendorMapping.platform == platform)
        return query.order_by(VendorMapping.alias_name).offset(offset).limit(limit).all()

    def count(self, search: str = None, platform: str = None) -> int:
        query = self._base_query()
        if search:
            query = query.filter(
                VendorMapping.alias_name.ilike(f"%{search}%")
                | VendorMapping.canonical_name.ilike(f"%{search}%")
            )
        if platform:
            query = query.filter(VendorMapping.platform == platform)
        return query.count()


class RuleRepository(TenantBaseRepository):
    """Routing rules for auto-assigning invoices to platforms."""
    model = Rule

    def get_by_id(self, rule_id: int) -> Optional[Rule]:
        return self._get_by_id(rule_id)

    def create(self, name: str, conditions_json: str, action_type: str,
               action_value: str, priority: int = 0, description: str = None,
               is_active: bool = True, created_by: int = None) -> Rule:
        record = Rule(
            name=name, description=description, priority=priority,
            is_active=is_active, conditions_json=conditions_json,
            action_type=action_type, action_value=action_value,
            created_by=created_by,
        )
        return self._create(record)

    def update(self, rule_id: int, **kwargs) -> Optional[Rule]:
        return self._update(rule_id, **kwargs)

    def delete(self, rule_id: int) -> bool:
        return self._delete(rule_id)

    def list_all(self, active_only: bool = False) -> List[Rule]:
        query = self._base_query()
        if active_only:
            query = query.filter(Rule.is_active == True)
        return query.order_by(Rule.priority.asc()).all()

    def reorder(self, rule_ids: List[int]):
        """Reorder rules by the given ID sequence."""
        for idx, rule_id in enumerate(rule_ids):
            record = self._get_by_id(rule_id)
            if record:
                record.priority = idx
                record.updated_at = datetime.utcnow()
        self.db.commit()


class DraftRepository(TenantBaseRepository):
    """Invoice drafts — the core workflow entity."""
    model = InvoiceDraft

    def get_by_id(self, draft_id: int) -> Optional[InvoiceDraft]:
        return self._get_by_id(draft_id)

    def get_by_invoice_id(self, invoice_id: int) -> Optional[InvoiceDraft]:
        """Get the active draft for an invoice (excludes rejected)."""
        return (
            self._base_query()
            .filter(InvoiceDraft.invoice_id == invoice_id)
            .filter(InvoiceDraft.status != "REJECTED")
            .first()
        )

    def create(self, **kwargs) -> InvoiceDraft:
        record = InvoiceDraft(**kwargs)
        return self._create(record)

    def update(self, draft_id: int, **kwargs) -> Optional[InvoiceDraft]:
        return self._update(draft_id, **kwargs)

    def list_all(self, status: str = None, push_to: str = None, source: str = None,
                 limit: int = 50, offset: int = 0) -> List[InvoiceDraft]:
        query = self._base_query()
        if status:
            query = query.filter(InvoiceDraft.status == status)
        if push_to:
            query = query.filter(InvoiceDraft.push_to == push_to)
        if source:
            query = query.filter(InvoiceDraft.source == source)
        return query.order_by(InvoiceDraft.created_at.desc()).offset(offset).limit(limit).all()

    def count(self, status: str = None, push_to: str = None, source: str = None) -> int:
        query = self._base_query()
        if status:
            query = query.filter(InvoiceDraft.status == status)
        if push_to:
            query = query.filter(InvoiceDraft.push_to == push_to)
        if source:
            query = query.filter(InvoiceDraft.source == source)
        return query.count()

    def count_by_status(self) -> dict:
        """Count drafts per status for the current tenant."""
        all_drafts = self._base_query().all()
        counts = {}
        for d in all_drafts:
            counts[d.status] = counts.get(d.status, 0) + 1
        return counts


class IntegrationRepository(TenantBaseRepository):
    """Platform integrations with encrypted credentials."""
    model = Integration

    def get_by_id(self, integration_id: int) -> Optional[Integration]:
        return self._get_by_id(integration_id)

    def get_by_platform(self, platform: str) -> Optional[Integration]:
        return self._base_query().filter(Integration.platform == platform).first()

    def create(self, platform: str, display_name: str, config_encrypted: str,
               is_enabled: bool = False, created_by: int = None) -> Integration:
        record = Integration(
            platform=platform, display_name=display_name,
            config_encrypted=config_encrypted, is_enabled=is_enabled,
            created_by=created_by,
        )
        return self._create(record)

    def update(self, integration_id: int, **kwargs) -> Optional[Integration]:
        return self._update(integration_id, **kwargs)

    def delete(self, integration_id: int) -> bool:
        return self._delete(integration_id)

    def list_all(self) -> List[Integration]:
        return self._base_query().order_by(Integration.platform).all()


class PlatformVendorRepository(TenantBaseRepository):
    """Vendors synced from billing platforms."""
    model = PlatformVendor

    def get_by_platform_vendor_id(self, platform: str, platform_vendor_id: str):
        return (
            self._base_query()
            .filter(PlatformVendor.platform == platform)
            .filter(PlatformVendor.platform_vendor_id == platform_vendor_id)
            .first()
        )

    def upsert(self, platform: str, platform_vendor_id: str, vendor_name: str,
               email: str = "", status: str = "active", raw_data: str = None):
        """Insert or update a platform vendor. Returns (record, is_new)."""
        existing = self.get_by_platform_vendor_id(platform, platform_vendor_id)
        if existing:
            existing.vendor_name = vendor_name
            existing.email = email or ""
            existing.status = status or "active"
            if raw_data is not None:
                existing.raw_data = raw_data
            existing.synced_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(existing)
            return existing, False

        record = PlatformVendor(
            platform=platform, platform_vendor_id=platform_vendor_id,
            vendor_name=vendor_name, email=email or "",
            status=status or "active", raw_data=raw_data,
            synced_at=datetime.utcnow(),
        )
        return self._create(record), True

    def list_by_platform(self, platform: str, search: str = None) -> list:
        query = self._base_query().filter(PlatformVendor.platform == platform)
        if search:
            query = query.filter(PlatformVendor.vendor_name.ilike(f"%{search}%"))
        return query.order_by(PlatformVendor.vendor_name).all()

    def count_by_platform(self, platform: str) -> int:
        return self._base_query().filter(PlatformVendor.platform == platform).count()

    def last_synced(self, platform: str):
        record = (
            self._base_query()
            .filter(PlatformVendor.platform == platform)
            .order_by(PlatformVendor.synced_at.desc())
            .first()
        )
        return record.synced_at if record else None


class ChartOfAccountRepository(TenantBaseRepository):
    """Chart of Accounts — synced from billing platforms, editable locally."""
    model = ChartOfAccount

    def create(self, **kwargs) -> ChartOfAccount:
        record = ChartOfAccount(**kwargs)
        return self._create(record)

    def get_by_id(self, account_id: int) -> Optional[ChartOfAccount]:
        return self._get_by_id(account_id)

    def get_by_platform_account(self, platform: str, platform_account_id: str) -> Optional[ChartOfAccount]:
        return (
            self._base_query()
            .filter(ChartOfAccount.platform == platform, ChartOfAccount.platform_account_id == platform_account_id)
            .first()
        )

    def get_default(self, sub_type: str, platform: str = None) -> Optional[ChartOfAccount]:
        """Get the default account for a given sub_type, optionally filtered by platform."""
        query = self._base_query().filter(
            ChartOfAccount.sub_type == sub_type, ChartOfAccount.is_default == True
        )
        if platform:
            query = query.filter(ChartOfAccount.platform == platform)
        return query.first()

    def get_by_hsn(self, hsn_code: str, platform: str = None) -> Optional[ChartOfAccount]:
        """Find account mapped to an HSN code."""
        query = self._base_query().filter(ChartOfAccount.hsn_codes.isnot(None))
        if platform:
            query = query.filter(ChartOfAccount.platform == platform)
        for acc in query.all():
            try:
                codes = json.loads(acc.hsn_codes) if acc.hsn_codes else []
                if hsn_code in codes:
                    return acc
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def list_all(self, platform: str = None, type_filter: str = None,
                 sub_type: str = None, active_only: bool = True,
                 limit: int = None, offset: int = 0) -> List[ChartOfAccount]:
        query = self._base_query()
        if active_only:
            query = query.filter(ChartOfAccount.is_active == True)
        if platform:
            query = query.filter(ChartOfAccount.platform == platform)
        if type_filter:
            query = query.filter(ChartOfAccount.type == type_filter)
        if sub_type:
            query = query.filter(ChartOfAccount.sub_type == sub_type)
        query = query.order_by(ChartOfAccount.platform, ChartOfAccount.code, ChartOfAccount.name)
        if limit is not None:
            query = query.offset(offset).limit(limit)
        return query.all()

    def count(self, platform: str = None, type_filter: str = None,
              sub_type: str = None, active_only: bool = True) -> int:
        query = self._base_query()
        if active_only:
            query = query.filter(ChartOfAccount.is_active == True)
        if platform:
            query = query.filter(ChartOfAccount.platform == platform)
        if type_filter:
            query = query.filter(ChartOfAccount.type == type_filter)
        if sub_type:
            query = query.filter(ChartOfAccount.sub_type == sub_type)
        return query.count()

    def update(self, account_id: int, **kwargs) -> Optional[ChartOfAccount]:
        return self._update(account_id, **kwargs)

    def sync_from_platform(self, platform: str, accounts: List[dict]) -> dict:
        """Upsert accounts synced from a billing platform.

        Preserves local edits (sub_type, hsn_codes, is_default) on existing records.
        Returns {created: int, updated: int, total: int}.
        """
        from datetime import datetime as dt
        created = updated = 0
        for acc in accounts:
            existing = self.get_by_platform_account(platform, acc["id"])
            if existing:
                # Update synced fields only, preserve local tags
                existing.name = acc.get("name", existing.name)
                existing.code = acc.get("code", existing.code or "")
                existing.type = acc.get("type", existing.type)
                existing.description = acc.get("description", existing.description)
                existing.is_active = acc.get("is_active", True)
                existing.parent_platform_id = acc.get("parent_id")
                existing.synced_at = dt.utcnow()
                existing.updated_at = dt.utcnow()
                self.db.commit()
                updated += 1
            else:
                self.create(
                    platform=platform,
                    platform_account_id=acc["id"],
                    code=acc.get("code", ""),
                    name=acc.get("name", ""),
                    type=acc.get("type", ""),
                    description=acc.get("description"),
                    is_active=acc.get("is_active", True),
                    parent_platform_id=acc.get("parent_id"),
                    synced_at=dt.utcnow(),
                )
                created += 1
        return {"created": created, "updated": updated, "total": created + updated}


class ExtractionLogRepository(TenantBaseRepository):
    """Append-only extraction log — one record per invoice parse (S.36 CGST Act retention)."""
    model = ExtractionLog

    def create(self, invoice_id: int, raw_llm_json: str, parser_mode: str = None) -> ExtractionLog:
        record = ExtractionLog(
            invoice_id=invoice_id,
            raw_llm_json=raw_llm_json,
            parser_mode=parser_mode,
        )
        self.db.add(record)
        self._stamp(record)
        self.db.flush()
        return record

    def get_by_invoice(self, invoice_id: int) -> List[ExtractionLog]:
        return self._base_query().filter(ExtractionLog.invoice_id == invoice_id).order_by(ExtractionLog.created_at).all()


class ComplianceAuditLogRepository(TenantBaseRepository):
    """Immutable audit trail for push overrides and compliance-critical actions."""
    model = AuditLog

    def log(self, entity_type: str, entity_id: int, action: str,
            actor_id: int = None, override_reason_code: str = None,
            override_reason: str = None, metadata: dict = None) -> AuditLog:
        record = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            override_reason_code=override_reason_code,
            override_reason=override_reason,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        self.db.add(record)
        self._stamp(record)
        self.db.flush()
        return record

    def get_by_entity(self, entity_type: str, entity_id: int) -> List[AuditLog]:
        return self._base_query().filter(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        ).order_by(AuditLog.created_at).all()
