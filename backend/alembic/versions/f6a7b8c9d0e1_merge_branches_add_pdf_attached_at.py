"""Merge d4e5f6a7b8c9 + e5f6a7b8c9d0; add pdf_attached_at to invoice_drafts

Revision ID: f6a7b8c9d0e1
Revises: d4e5f6a7b8c9, e5f6a7b8c9d0
Create Date: 2026-05-06 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = ("d4e5f6a7b8c9", "e5f6a7b8c9d0")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoice_drafts", sa.Column("pdf_attached_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    op.drop_column("invoice_drafts", "pdf_attached_at")
