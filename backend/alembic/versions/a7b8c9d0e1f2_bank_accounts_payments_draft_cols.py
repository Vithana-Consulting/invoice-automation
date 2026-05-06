"""Add company_bank_accounts, invoice_payments tables and bank/payment cols to invoice_drafts

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-06 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns on invoice_drafts
    op.add_column("invoice_drafts", sa.Column("bank_details_json", sa.Text, nullable=True))
    op.add_column("invoice_drafts", sa.Column("payment_status", sa.String(20), nullable=True))
    op.add_column("invoice_drafts", sa.Column("amount_paid", sa.Numeric(15, 2), nullable=True, server_default="0"))
    op.add_column("invoice_drafts", sa.Column("amount_due", sa.Numeric(15, 2), nullable=True))

    # company_bank_accounts
    op.create_table(
        "company_bank_accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=False),
        sa.Column("account_number", sa.String(30), nullable=False),
        sa.Column("account_number_masked", sa.String(20), nullable=False),
        sa.Column("ifsc_code", sa.String(15), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False, server_default="CURRENT"),
        sa.Column("account_alias", sa.String(50), nullable=False),
        sa.Column("is_default", sa.Boolean, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_company_bank_accounts_company_id", "company_bank_accounts", ["company_id"])

    # invoice_payments
    op.create_table(
        "invoice_payments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("draft_id", sa.Integer, sa.ForeignKey("invoice_drafts.id"), nullable=True),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("payment_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(5), server_default="INR"),
        sa.Column("payment_reference", sa.String(100), nullable=True),
        sa.Column("cheque_number", sa.String(20), nullable=True),
        sa.Column("cheque_date", sa.Date, nullable=True),
        sa.Column("cheque_clearing_date", sa.Date, nullable=True),
        sa.Column("payer_bank_account_id", sa.Integer, sa.ForeignKey("company_bank_accounts.id"), nullable=True),
        sa.Column("payer_bank_name", sa.String(100), nullable=True),
        sa.Column("payer_account_number_masked", sa.String(30), nullable=True),
        sa.Column("payee_account_number", sa.String(30), nullable=True),
        sa.Column("payee_ifsc_code", sa.String(15), nullable=True),
        sa.Column("payee_upi_id", sa.String(100), nullable=True),
        sa.Column("invoice_total_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("tds_amount", sa.Numeric(15, 2), server_default="0"),
        sa.Column("tds_section", sa.String(20), nullable=True),
        sa.Column("advance_adjusted", sa.Numeric(15, 2), server_default="0"),
        sa.Column("advance_reference", sa.String(100), nullable=True),
        sa.Column("payment_status", sa.String(20), server_default="INITIATED"),
        sa.Column("payment_type", sa.String(30), server_default="FULL"),
        sa.Column("remarks", sa.Text, nullable=True),
        sa.Column("recorded_by_email", sa.String(255), nullable=False),
        sa.Column("recorded_by_name", sa.String(255), nullable=True),
        sa.Column("recorded_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_invoice_payments_company_id", "invoice_payments", ["company_id"])
    op.create_index("ix_invoice_payments_invoice_id", "invoice_payments", ["invoice_id"])
    op.create_index("ix_invoice_payments_draft_id", "invoice_payments", ["draft_id"])


def downgrade() -> None:
    op.drop_table("invoice_payments")
    op.drop_table("company_bank_accounts")
    op.drop_column("invoice_drafts", "amount_due")
    op.drop_column("invoice_drafts", "amount_paid")
    op.drop_column("invoice_drafts", "payment_status")
    op.drop_column("invoice_drafts", "bank_details_json")
