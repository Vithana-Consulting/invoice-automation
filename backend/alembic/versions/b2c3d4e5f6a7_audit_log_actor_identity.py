"""Add actor_email, actor_name, actor_role to audit_logs for point-in-time identity

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-03 10:00:00.000000

Rationale: actor_id (FK to users) is insufficient for a compliance audit trail —
user email and role can change after the fact. These columns are stamped at write
time so the audit record is self-contained and does not require a FK join to
reconstruct who did what and with what authority.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_logs', sa.Column('actor_email', sa.String(length=255), nullable=True))
    op.add_column('audit_logs', sa.Column('actor_name', sa.String(length=255), nullable=True))
    op.add_column('audit_logs', sa.Column('actor_role', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_logs', 'actor_role')
    op.drop_column('audit_logs', 'actor_name')
    op.drop_column('audit_logs', 'actor_email')
