"""Dedup hardening: per-tenant content_hash uniqueness + lookup indexes

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-05 00:00:01.000000

- invoices.content_hash was GLOBALLY unique (inline unique=True -> MySQL unique
  index named ``content_hash``), but get_by_content_hash() is tenant-scoped.
  The same file arriving for a second company passed the dedup check then 500'd
  on the global constraint. Swap to a per-tenant composite unique
  (company_id, content_hash).
- Add composite indexes to support duplicate-detection lookups.

Pre-check before applying (must return no rows):
  SELECT company_id, content_hash, COUNT(*) c FROM invoices
  WHERE content_hash IS NOT NULL
  GROUP BY company_id, content_hash HAVING c > 1;
"""
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade():
    # Per-tenant content_hash uniqueness (replaces the global unique index).
    op.drop_index("content_hash", table_name="invoices")
    op.create_unique_constraint(
        "uq_invoices_company_content_hash", "invoices", ["company_id", "content_hash"]
    )

    # Duplicate-detection lookup support.
    op.create_index(
        "ix_invoices_company_vendor_invnum",
        "invoices",
        ["company_id", "vendor_name", "invoice_number"],
    )
    op.create_index(
        "ix_drafts_company_vendor_invnum_status",
        "invoice_drafts",
        ["company_id", "vendor_name", "invoice_number", "status"],
    )


def downgrade():
    op.drop_index("ix_drafts_company_vendor_invnum_status", table_name="invoice_drafts")
    op.drop_index("ix_invoices_company_vendor_invnum", table_name="invoices")
    op.drop_constraint("uq_invoices_company_content_hash", "invoices", type_="unique")
    op.create_index("content_hash", "invoices", ["content_hash"], unique=True)
