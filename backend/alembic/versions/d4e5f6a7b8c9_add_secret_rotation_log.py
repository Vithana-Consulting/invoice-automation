"""Add secret_rotation_log table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-06 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'secret_rotation_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('secret_key', sa.String(length=100), nullable=False),
        sa.Column('rotated_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column('rotated_by', sa.String(length=255), nullable=True),
        sa.Column('rotation_method', sa.String(length=50), nullable=False),
        sa.Column('previous_key_hash', sa.String(length=64), nullable=True),
        sa.Column('new_key_hash', sa.String(length=64), nullable=True),
        sa.Column('grace_period_seconds', sa.Integer(), nullable=True),
        sa.Column('grace_expires_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_secret_rotation_log_secret_key', 'secret_rotation_log', ['secret_key'])


def downgrade() -> None:
    op.drop_index('ix_secret_rotation_log_secret_key', table_name='secret_rotation_log')
    op.drop_table('secret_rotation_log')
