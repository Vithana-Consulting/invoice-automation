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
    Date,
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
    legal_name = Column(String(500), nullable=True)  # Full legal name (e.g. "ACME PRIVATE LIMITED") — used as buyer hint in parser
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
    thread_id = Column(String(255), nullable=True, index=True)  # Gmail thread this message belongs to
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
    __table_args__ = (
        # Per-tenant content_hash uniqueness (NOT global — the same file may
        # legitimately arrive for two different companies).
        Index("uq_invoices_company_content_hash", "company_id", "content_hash", unique=True),
        # Supports duplicate-detection lookups by vendor + invoice number.
        Index("ix_invoices_company_vendor_invnum", "company_id", "vendor_name", "invoice_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    email_id = Column(Integer, ForeignKey("processed_emails.id"), nullable=True)
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), default="")
    file_type = Column(String(20), default="pdf")
    content_hash = Column(String(64), nullable=True)  # uniqueness is per-tenant (see __table_args__)

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

    # Cloud storage
    drive_file_id = Column(String(255), nullable=True)

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


class AdhocInvoiceUpload(Base):
    """Ad-hoc / manually uploaded invoices, parsed for one-off export.

    Deliberately SEPARATE from `invoices`/`invoice_drafts` — these never enter
    the Gmail ingestion pipeline, never become drafts, and never appear on the
    Invoices page. Used by the Upload tab (parse → table → Excel export).
    """
    __tablename__ = "adhoc_invoice_uploads"
    __table_args__ = (
        # Per-tenant dedup of identical re-uploads.
        Index("uq_adhoc_company_content_hash", "company_id", "content_hash", unique=True),
        # Listing newest-first per tenant.
        Index("ix_adhoc_company_created", "company_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    uploaded_by_email = Column(String(255), nullable=True)

    # File metadata
    file_name = Column(String(255), default="")
    file_path = Column(String(500), nullable=True)
    file_type = Column(String(20), default="pdf")
    content_hash = Column(String(64), nullable=True)

    # Parsed fields (mirror app.models.domain.Invoice)
    invoice_number = Column(String(100), nullable=True)
    vendor_name = Column(String(500), nullable=True)
    invoice_date = Column(String(20), nullable=True)
    due_date = Column(String(20), nullable=True)
    subtotal = Column(Numeric(15, 2), nullable=True)
    tax_amount = Column(Numeric(15, 2), nullable=True)
    total_amount = Column(Numeric(15, 2), nullable=True)
    currency = Column(String(5), default="INR")
    gst_number = Column(String(20), nullable=True)
    pan_number = Column(String(15), nullable=True)
    place_of_supply = Column(String(5), nullable=True)

    # Raw / structured extras
    line_items_json = Column(Text, nullable=True)
    tax_breakup_json = Column(Text, nullable=True)
    bank_details_json = Column(Text, nullable=True)
    raw_json = Column(Text, nullable=True)

    parser_mode = Column(String(30), nullable=True)
    parse_status = Column(String(20), default="PARSED")  # PARSED | FAILED
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class VendorCache(Base):
    """Cached vendor lookups (legacy Day2 — kept for compat)."""
    __tablename__ = "vendor_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    vendor_name = Column(String(500), nullable=False)
    zoho_vendor_id = Column(String(100), nullable=True)
    gst_number = Column(String(20), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CompanyViewPreference(Base):
    """Per-org saved grid layout (column order / visibility / width) for a named view.

    Shared across all members of the company — one row per (company_id, view_key),
    e.g. view_key="invoices". `columns_json` stores the AG Grid column-state array
    ([{colId, hide, width, ...}]) verbatim so the saved layout round-trips.
    """
    __tablename__ = "company_view_prefs"
    __table_args__ = (
        Index("uq_company_view_key", "company_id", "view_key", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    view_key = Column(String(50), nullable=False)
    columns_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    __table_args__ = (
        # Supports the pre-push duplicate lookup by vendor + invoice number + status.
        Index(
            "ix_drafts_company_vendor_invnum_status",
            "company_id", "vendor_name", "invoice_number", "status",
        ),
    )

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
    pdf_attached_at = Column(DateTime, nullable=True)

    # Bank & payment fields
    bank_details_json = Column(Text, nullable=True)      # vendor bank details from invoice PDF
    payment_status = Column(String(20), nullable=True)   # UNPAID/PARTIALLY_PAID/FULLY_PAID
    amount_paid = Column(Numeric(15, 2), nullable=True, default=0)
    amount_due = Column(Numeric(15, 2), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    invoice = relationship("InvoiceRecord", back_populates="drafts")
    matched_rule = relationship("Rule", foreign_keys=[push_to_rule_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    account = relationship("ChartOfAccount", foreign_keys=[account_id])
    payments = relationship("InvoicePayment", back_populates="draft", foreign_keys="InvoicePayment.draft_id")


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

    # TDS defaults — when a draft uses this account, these drive bill-level TDS on push.
    # Resolved at push-time: tds_section + tds_rate → platform_tds_taxes.platform_tax_id.
    tds_section = Column(String(20), nullable=True)  # 194J | 194C | 194I | 194H | 194Q ...
    tds_rate = Column(Numeric(5, 2), nullable=True)  # editable percent, e.g. 10.00
    tds_tax_id = Column(String(100), nullable=True)  # cached platform tax id (optional override)

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


class PlatformTdsTax(Base):
    """TDS tax masters synced from billing platforms (Zoho, QuickBooks).

    Resolved at push-time from chart_of_accounts.{tds_section, tds_rate}
    → matching row here → platform_tax_id sent on the bill payload.
    """
    __tablename__ = "platform_tds_taxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    platform = Column(String(30), nullable=False)
    platform_tax_id = Column(String(100), nullable=False)
    tax_name = Column(String(200), nullable=False)
    section = Column(String(20), nullable=True)   # 194J | 194C | ...
    rate = Column(Numeric(5, 2), nullable=True)
    tax_type = Column(String(30), nullable=True)  # tds | tcs | etc.
    is_active = Column(Boolean, default=True)
    raw_data = Column(Text, nullable=True)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_platform_tds_taxes_unique", "company_id", "platform", "platform_tax_id", unique=True),
        Index("ix_platform_tds_taxes_lookup", "company_id", "platform", "section", "rate"),
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


class SecretRotationLog(Base):
    """Immutable audit log of secret rotation events.

    Insert-only. Never updated or deleted.
    """
    __tablename__ = "secret_rotation_log"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    secret_key           = Column(String(100), nullable=False, index=True)
    rotated_at           = Column(DateTime, nullable=False, default=datetime.utcnow)
    rotated_by           = Column(String(255), nullable=True)
    rotation_method      = Column(String(50), nullable=False, default="auto")
    previous_key_hash    = Column(String(64), nullable=True)   # SHA-256 of OLD value
    new_key_hash         = Column(String(64), nullable=True)   # SHA-256 of NEW value
    grace_period_seconds = Column(Integer, nullable=True)
    grace_expires_at     = Column(DateTime, nullable=True)
    notes                = Column(Text, nullable=True)
    # NOTE: no updated_at — insert-only audit record


class CompanyBankAccount(Base):
    """Entvin's own bank accounts — the 'FROM' accounts when paying vendors."""
    __tablename__ = "company_bank_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    bank_name = Column(String(100), nullable=False)
    account_number = Column(String(30), nullable=False)
    account_number_masked = Column(String(20), nullable=False)   # e.g. "XXXX 4521"
    ifsc_code = Column(String(15), nullable=False)
    account_type = Column(String(20), nullable=False, default="CURRENT")  # CURRENT/SAVINGS/OVERDRAFT
    account_alias = Column(String(50), nullable=False)           # e.g. "HDFC Ops Account"
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    payments = relationship("InvoicePayment", back_populates="payer_bank_account")


class InvoicePayment(Base):
    """Records a payment made against an invoice draft."""
    __tablename__ = "invoice_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    draft_id = Column(Integer, ForeignKey("invoice_drafts.id"), nullable=True, index=True)

    payment_method = Column(String(20), nullable=False)   # NEFT/RTGS/IMPS/UPI/CHEQUE/DD/CASH
    payment_date = Column(Date, nullable=False)
    payment_amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(5), default="INR")
    payment_reference = Column(String(100), nullable=True)   # UTR for NEFT/RTGS, UPI txn ID
    cheque_number = Column(String(20), nullable=True)
    cheque_date = Column(Date, nullable=True)
    cheque_clearing_date = Column(Date, nullable=True)

    # Payer (Entvin) side
    payer_bank_account_id = Column(Integer, ForeignKey("company_bank_accounts.id"), nullable=True)
    payer_bank_name = Column(String(100), nullable=True)
    payer_account_number_masked = Column(String(30), nullable=True)

    # Payee (Vendor) side
    payee_account_number = Column(String(30), nullable=True)
    payee_ifsc_code = Column(String(15), nullable=True)
    payee_upi_id = Column(String(100), nullable=True)

    # Amounts
    invoice_total_amount = Column(Numeric(15, 2), nullable=False)
    tds_amount = Column(Numeric(15, 2), default=0)
    tds_section = Column(String(20), nullable=True)
    advance_adjusted = Column(Numeric(15, 2), default=0)
    advance_reference = Column(String(100), nullable=True)

    payment_status = Column(String(20), default="INITIATED")   # INITIATED/PENDING_CLEARANCE/CLEARED/BOUNCED/CANCELLED
    payment_type = Column(String(30), default="FULL")          # FULL/PARTIAL/ADVANCE_ADJUSTMENT

    remarks = Column(Text, nullable=True)
    recorded_by_email = Column(String(255), nullable=False)
    recorded_by_name = Column(String(255), nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    draft = relationship("InvoiceDraft", back_populates="payments", foreign_keys=[draft_id])
    payer_bank_account = relationship("CompanyBankAccount", back_populates="payments")
