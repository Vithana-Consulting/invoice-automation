"""Add TDS columns to chart_of_accounts and create platform_tds_taxes table.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-09 12:45:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # COA TDS defaults — drive bill-level TDS when this account is used
    op.add_column("chart_of_accounts", sa.Column("tds_section", sa.String(20), nullable=True))
    op.add_column("chart_of_accounts", sa.Column("tds_rate", sa.Numeric(5, 2), nullable=True))
    op.add_column("chart_of_accounts", sa.Column("tds_tax_id", sa.String(100), nullable=True))

    # Platform TDS tax master — synced from Zoho/QB, mapped to COA via section+rate
    op.create_table(
        "platform_tds_taxes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("platform_tax_id", sa.String(100), nullable=False),
        sa.Column("tax_name", sa.String(200), nullable=False),
        sa.Column("section", sa.String(20), nullable=True),
        sa.Column("rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("tax_type", sa.String(30), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="1"),
        sa.Column("raw_data", sa.Text, nullable=True),
        sa.Column("synced_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_platform_tds_taxes_unique",
        "platform_tds_taxes",
        ["company_id", "platform", "platform_tax_id"],
        unique=True,
    )
    op.create_index(
        "ix_platform_tds_taxes_lookup",
        "platform_tds_taxes",
        ["company_id", "platform", "section", "rate"],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_tds_taxes_lookup", table_name="platform_tds_taxes")
    op.drop_index("ix_platform_tds_taxes_unique", table_name="platform_tds_taxes")
    op.drop_table("platform_tds_taxes")
    op.drop_column("chart_of_accounts", "tds_tax_id")
    op.drop_column("chart_of_accounts", "tds_rate")
    op.drop_column("chart_of_accounts", "tds_section")
