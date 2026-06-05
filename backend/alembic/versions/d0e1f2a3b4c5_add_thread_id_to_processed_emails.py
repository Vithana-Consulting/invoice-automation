"""Add thread_id to processed_emails (thread-aware ingestion)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processed_emails", sa.Column("thread_id", sa.String(255), nullable=True))
    op.create_index("ix_processed_emails_thread_id", "processed_emails", ["thread_id"])


def downgrade():
    op.drop_index("ix_processed_emails_thread_id", table_name="processed_emails")
    op.drop_column("processed_emails", "thread_id")
