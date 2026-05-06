"""add drive_file_id to invoices

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-06 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("drive_file_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("invoices", "drive_file_id")
