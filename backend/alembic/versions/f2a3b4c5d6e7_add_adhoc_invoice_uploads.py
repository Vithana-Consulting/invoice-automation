"""Add adhoc_invoice_uploads table (ad-hoc upload → parse → Excel)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-05 00:00:02.000000

Separate from invoices/invoice_drafts — ad-hoc manual uploads parsed for one-off
Excel export, never entering the Gmail ingestion pipeline or the Invoices page.
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "adhoc_invoice_uploads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_email", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("file_type", sa.String(length=20), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=True),
        sa.Column("vendor_name", sa.String(length=500), nullable=True),
        sa.Column("invoice_date", sa.String(length=20), nullable=True),
        sa.Column("due_date", sa.String(length=20), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=5), nullable=True),
        sa.Column("gst_number", sa.String(length=20), nullable=True),
        sa.Column("pan_number", sa.String(length=15), nullable=True),
        sa.Column("place_of_supply", sa.String(length=5), nullable=True),
        sa.Column("line_items_json", sa.Text(), nullable=True),
        sa.Column("tax_breakup_json", sa.Text(), nullable=True),
        sa.Column("bank_details_json", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("parser_mode", sa.String(length=30), nullable=True),
        sa.Column("parse_status", sa.String(length=20), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_adhoc_invoice_uploads_company_id", "adhoc_invoice_uploads", ["company_id"])
    op.create_unique_constraint(
        "uq_adhoc_company_content_hash", "adhoc_invoice_uploads", ["company_id", "content_hash"]
    )
    op.create_index(
        "ix_adhoc_company_created", "adhoc_invoice_uploads", ["company_id", "created_at"]
    )


def downgrade():
    op.drop_index("ix_adhoc_company_created", table_name="adhoc_invoice_uploads")
    op.drop_constraint("uq_adhoc_company_content_hash", "adhoc_invoice_uploads", type_="unique")
    op.drop_index("ix_adhoc_invoice_uploads_company_id", table_name="adhoc_invoice_uploads")
    op.drop_table("adhoc_invoice_uploads")
