"""Database models for Vithana Accounting Platform.

Multi-tenant architecture:
  - All tenant-scoped tables have a `company_id` column
  - Queries are filtered by company_id via TenantBaseRepository
  - Users and Companies are global (no company_id)
  - CompanyMember links users to companies with roles
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ─── Global Models (no company_id) ────────────────────────────────────────


class SystemConfig(Base):
    """App-level key-value configuration stored in DB.

    Used for settings that were previously in .env but need to be
    manageable at runtime without redeployment (e.g., OAuth credentials).
    """
    __tablename__ = "system_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    is_secret = Column(Boolean, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Company(Base):
    """A tenant — each company has isolated data via company_id filtering."""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    domain = Column(String(255), unique=True, nullable=True, index=True)  # email domain → company lookup
    gst_number = Column(String(20), nullable=True)  # Company's GSTIN for invoice validation
    pan_number = Column(String(15), nullable=True)  # Company's PAN for invoice validation
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = relationship("CompanyMember", back_populates="company")


class User(Base):
    """Authenticated user — can belong to multiple companies."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), default="")
    picture_url = Column(String(500), nullable=True)
    google_sub = Column(String(255), unique=True, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    memberships = relationship("CompanyMember", back_populates="user")


class CompanyMember(Base):
    """Links users to companies with role-based access."""
    __tablename__ = "company_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    role = Column(String(50), nullable=False, default="member")  # owner, admin, member
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="memberships")
    company = relationship("Company", back_populates="members")

    __table_args__ = (
        Index("ix_company_members_unique", "user_id", "company_id", unique=True),
    )


# ─── Tenant-Scoped Models (all have company_id) ───────────────────────────


class ProcessedEmail(Base):
    """Emails fetched from Gmail or other sources."""
    __tablename__ = "processed_emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    message_id = Column(String(255), unique=True, nullable=False)
    subject = Column(String(500), default="")
    sender = Column(String(255), default="")
    received_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    attachment_count = Column(Integer, default=0)
    status = Column(String(50), default="FETCHED")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    invoices = relationship("InvoiceRecord", back_populates="email")


class InvoiceRecord(Base):
    """Raw invoice files with parsed metadata."""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    email_id = Column(Integer, ForeignKey("processed_emails.id"), nullable=True)
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), default="")
    file_type = Column(String(20), default="pdf")
    content_hash = Column(String(64), unique=True, nullable=True)

    # Parsed fields
    invoice_number = Column(String(100), nullable=True)
    vendor_name = Column(String(500), nullable=True)
    invoice_date = Column(String(20), nullable=True)
    due_date = Column(String(20), nullable=True)
    total_amount = Column(Numeric(15, 2), nullable=True)
    tax_amount = Column(Numeric(15, 2), nullable=True)
    subtotal = Column(Numeric(15, 2), nullable=True)
    gst_number = Column(String(20), nullable=True)       # vendor/seller GSTIN
    buyer_gst_number = Column(String(20), nullable=True) # buyer/company GSTIN
    pan_number = Column(String(15), nullable=True)       # vendor/seller PAN
    buyer_pan_number = Column(String(15), nullable=True) # buyer/company PAN
    vendor_address = Column(Text, nullable=True)         # vendor/seller full address
    uan_number = Column(String(20), nullable=True)
    currency = Column(String(5), default="INR")
    line_items_json = Column(Text, nullable=True)
    tax_breakup_json = Column(Text, nullable=True)  # {"cgst_rate":9,"cgst_amount":450,...}
    bank_details_json = Column(Text, nullable=True)  # {"bank_name":...,"account_number":...}
    invoice_type = Column(String(20), nullable=True)  # INBOUND (purchase) | OUTBOUND (sale)
    raw_text = Column(Text, nullable=True)
    parser_mode = Column(String(30), nullable=True)
    parsing_status = Column(String(20), default="PENDING")
    validation_errors = Column(Text, nullable=True)
    confidence_scores = Column(Text, nullable=True)

    place_of_supply = Column(String(5), nullable=True)

    # Source tracking
    source = Column(String(50), default="gmail")
    source_ref = Column(String(255), nullable=True)

    # Legacy Zoho fields (kept for backward compat)
    zoho_push_status = Column(String(20), nullable=True)
    zoho_bill_id = Column(String(100), nullable=True)
    zoho_vendor_id = Column(String(100), nullable=True)
    zoho_pushed_at = Column(DateTime, nullable=True)
    zoho_error = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    email = relationship("ProcessedEmail", back_populates="invoices")
    drafts = relationship("InvoiceDraft", back_populates="invoice")


class VendorCache(Base):
    """Cached vendor lookups (legacy Day2 — kept for compat)."""
    __tablename__ = "vendor_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    vendor_name = Column(String(500), nullable=False)
    zoho_vendor_id = Column(String(100), nullable=True)
    gst_number = Column(String(20), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class LegacyAuditLog(Base):
    """Tracks all significant actions for debugging and compliance (legacy table)."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=True)
    action = Column(String(100), nullable=False, index=True)
    details = Column(Text, nullable=True)
    status = Column(String(20), default="success")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class VendorMapping(Base):
    """Maps invoice vendor names to platform-specific canonical names.

    Example:
      alias_name="Google Private Limited" → canonical_name="Google PVTL" (platform=zoho)
      alias_name="Google Private Limited" → canonical_name="Google LLC"  (platform=quickbooks)
    """
    __tablename__ = "vendor_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    alias_name = Column(String(500), nullable=False, index=True)
    canonical_name = Column(String(500), nullable=False)
    platform = Column(String(50), nullable=False, index=True)
    platform_vendor_id = Column(String(255), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    is_composition_vendor = Column(Boolean, default=False, nullable=False, server_default="0")

    creator = relationship("User", foreign_keys=[created_by])


class Rule(Base):
    """Routing rules for auto-assigning invoices to billing platforms.

    Rules are evaluated in priority order (lower = higher priority).
    First match wins.
    """
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    conditions_json = Column(Text, nullable=False)
    action_type = Column(String(50), default="set_push_to")
    action_value = Column(String(100), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])


class InvoiceDraft(Base):
    """Editable invoice snapshot ready for review and push to billing platforms.

    Lifecycle: PENDING_REVIEW → PENDING_VENDOR → APPROVED → PUSHED
                                                          → PUSH_FAILED
                              → REJECTED
    """
    __tablename__ = "invoice_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)

    # Editable snapshot
    vendor_name = Column(String(500), nullable=True)
    resolved_vendor_name = Column(String(500), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    invoice_date = Column(String(20), nullable=True)
    due_date = Column(String(20), nullable=True)
    total_amount = Column(Numeric(15, 2), nullable=True)
    tax_amount = Column(Numeric(15, 2), nullable=True)
    currency = Column(String(5), default="INR")
    line_items_json = Column(Text, nullable=True)

    # Routing
    push_to = Column(String(50), nullable=True, index=True)
    push_to_rule_id = Column(Integer, ForeignKey("rules.id"), nullable=True)
    source = Column(String(50), default="gmail")

    # Status tracking
    status = Column(String(30), default="PENDING_REVIEW")
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    push_error = Column(Text, nullable=True)
    pushed_at = Column(DateTime, nullable=True)
    external_bill_id = Column(String(255), nullable=True)
    validation_warnings = Column(Text, nullable=True)  # JSON array of {code, message} — parsing warnings
    validation_errors = Column(Text, nullable=True)   # JSON array of ValidationResult dicts from pre-push check
    tax_breakup_json = Column(Text, nullable=True)
    invoice_type = Column(String(20), nullable=True)  # INBOUND | OUTBOUND
    account_id = Column(Integer, ForeignKey("chart_of_accounts.id"), nullable=True)
    place_of_supply = Column(String(5), nullable=True)   # 2-char GST state code
    itc_status = Column(String(20), nullable=True, default="UNCONFIRMED")  # UNCONFIRMED/CONFIRMED/INELIGIBLE/NA
    tds_applicable = Column(Boolean, nullable=True)      # manual checkbox

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    invoice = relationship("InvoiceRecord", back_populates="drafts")
    matched_rule = relationship("Rule", foreign_keys=[push_to_rule_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    account = relationship("ChartOfAccount", foreign_keys=[account_id])


class ChartOfAccount(Base):
    """Chart of Accounts — synced from billing platforms (Zoho, QuickBooks, Tally).

    These are the ACTUAL accounts from the user's accounting platform.
    Synced via API, editable locally for tagging (sub_type, hsn_codes).

    The AI uses sub_type + hsn_codes to auto-assign the correct account
    when pushing invoices to the platform.
    """
    __tablename__ = "chart_of_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Synced from platform
    platform = Column(String(30), nullable=False)  # zoho | quickbooks | tally
    platform_account_id = Column(String(100), nullable=False)  # ID on the platform
    code = Column(String(20), nullable=False, default="")  # account code from platform
    name = Column(String(200), nullable=False)  # account name from platform
    type = Column(String(50), nullable=False)  # platform's account type (e.g., "expense", "other_current_asset")
    description = Column(Text, nullable=True)  # description from platform
    parent_platform_id = Column(String(100), nullable=True)  # parent account ID on platform
    is_active = Column(Boolean, default=True)

    # Local editable fields (user tags these after sync)
    sub_type = Column(String(30), nullable=True)  # PURCHASE | SALE | TAX_CGST | TAX_SGST | TAX_IGST | TAX_CESS
    hsn_codes = Column(Text, nullable=True)  # JSON array of HSN codes mapped to this account
    is_default = Column(Boolean, default=False)  # default account for this sub_type on this platform

    synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_coa_company_platform_account", "company_id", "platform", "platform_account_id", unique=True),
    )


class PlatformVendor(Base):
    """Vendors synced from billing platforms (Zoho, QuickBooks, etc.)."""
    __tablename__ = "platform_vendors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    platform = Column(String(50), nullable=False, index=True)
    platform_vendor_id = Column(String(255), nullable=False)
    vendor_name = Column(String(500), nullable=False)
    email = Column(String(255), default="")
    status = Column(String(50), default="active")
    raw_data = Column(Text, nullable=True)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_platform_vendors_unique", "company_id", "platform", "platform_vendor_id", unique=True),
    )


class Integration(Base):
    """Configured platform integrations with encrypted credentials."""
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    platform = Column(String(50), nullable=False, index=True)
    display_name = Column(String(255), default="")
    config_encrypted = Column(Text, nullable=False)
    is_enabled = Column(Boolean, default=False)
    health_status = Column(String(20), default="UNKNOWN")
    health_checked_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])


class ExtractionLog(Base):
    """Immutable record of raw LLM extraction output per invoice.

    Insert-only — never updated. Retained per S.36 CGST Act (72-month).
    """
    __tablename__ = "extraction_logs"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    company_id     = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    invoice_id     = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    raw_llm_json   = Column(Text, nullable=False)          # immutable — written once
    parser_mode    = Column(String(100), nullable=True)
    created_at     = Column(DateTime, nullable=False, default=datetime.utcnow)
    # NOTE: no updated_at — this table is append-only per S.36 CGST Act (72-month retention)


class AuditLog(Base):
    """Immutable audit trail for push overrides and compliance-critical actions.

    Insert-only — never updated or deleted.
    """
    __tablename__ = "audit_logs"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    company_id           = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    entity_type          = Column(String(50), nullable=False)  # "invoice_draft", "vendor_mapping"
    entity_id            = Column(Integer, nullable=False, index=True)
    action               = Column(String(100), nullable=False)  # "push_override", "reconciliation_override"
    actor_id             = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Denormalized point-in-time identity — do NOT resolve via FK join at read time
    # (user email/role can change after the fact; these are stamped at write time)
    actor_email          = Column(String(255), nullable=True)
    actor_name           = Column(String(255), nullable=True)
    actor_role           = Column(String(50), nullable=True)
    override_reason_code = Column(String(100), nullable=True)
    override_reason      = Column(Text, nullable=True)
    metadata_json        = Column(Text, nullable=True)
    created_at           = Column(DateTime, nullable=False, default=datetime.utcnow)
    # NOTE: no updated_at, no soft delete — immutable audit record
