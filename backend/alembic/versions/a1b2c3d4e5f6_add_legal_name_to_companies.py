"""Add legal_name to companies

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-05-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = ("f6a7b8c9d0e1",)
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("companies", sa.Column("legal_name", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("companies", "legal_name")
