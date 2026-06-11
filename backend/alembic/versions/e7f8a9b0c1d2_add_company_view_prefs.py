"""Add company_view_prefs table (per-org saved grid column layout)

Revision ID: e7f8a9b0c1d2
Revises: f2a3b4c5d6e7
Create Date: 2026-06-11 00:00:00.000000

Stores one column-layout per (company_id, view_key) so a company's chosen
invoice-grid columns (order / visibility / width) are shared by all its members.
"""
from alembic import op
import sqlalchemy as sa

revision = "e7f8a9b0c1d2"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_view_prefs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("view_key", sa.String(length=50), nullable=False),
        sa.Column("columns_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_view_prefs_company_id", "company_view_prefs", ["company_id"]
    )
    op.create_unique_constraint(
        "uq_company_view_key", "company_view_prefs", ["company_id", "view_key"]
    )


def downgrade():
    op.drop_constraint("uq_company_view_key", "company_view_prefs", type_="unique")
    op.drop_index("ix_company_view_prefs_company_id", table_name="company_view_prefs")
    op.drop_table("company_view_prefs")
