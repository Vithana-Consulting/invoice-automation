"""Add legal_name to companies

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-12 00:00:00.000000

Note: this migration previously reused revision id ``a1b2c3d4e5f6`` (already
owned by the gstin/itc migration), which produced a duplicate-revision warning
and a dangling second head. It has been re-issued with a unique id and
linearized onto the tds head (``b8c9d0e1f2a3``).
"""
from alembic import op
import sqlalchemy as sa

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("companies", sa.Column("legal_name", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("companies", "legal_name")
