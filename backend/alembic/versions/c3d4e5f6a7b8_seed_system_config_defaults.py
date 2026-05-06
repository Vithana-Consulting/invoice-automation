"""Seed system_config with default admin-configurable settings

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-06 10:00:00.000000

Seeds the system_config table with default values for all admin-editable
settings. Values already set (e.g., from a previous run) are NOT overwritten.
"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default values — safe defaults, no secrets
DEFAULTS = {
    "PARSER_MODE": "tesseract",
    "LLM_PROVIDER": "openai",
    "LLM_MODEL": "gpt-4o",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "",
    "LLAMAPARSE_API_KEY": "",
    "GOOGLE_CLIENT_ID": "",
    "GOOGLE_CLIENT_SECRET": "",
    "GOOGLE_REDIRECT_URI": "http://localhost:8001/api/auth/google/callback",
    "FRONTEND_URL": "http://localhost:3000",
    "DEBUG": "false",
    "MAX_RETRIES": "3",
}

SECRET_KEYS = {"LLM_API_KEY", "LLAMAPARSE_API_KEY", "GOOGLE_CLIENT_SECRET"}


def upgrade() -> None:
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("is_secret", sa.Boolean),
        sa.column("updated_at", sa.DateTime),
    )
    conn = op.get_bind()
    now = datetime.utcnow()

    for key, value in DEFAULTS.items():
        # Only insert if not already set (don't overwrite admin changes)
        exists = conn.execute(
            sa.select(sa.text("1")).select_from(system_config).where(
                system_config.c.key == key
            )
        ).first()
        if not exists:
            conn.execute(
                system_config.insert().values(
                    key=key,
                    value=value,
                    is_secret=key in SECRET_KEYS,
                    updated_at=now,
                )
            )


def downgrade() -> None:
    conn = op.get_bind()
    system_config = sa.table("system_config", sa.column("key", sa.String))
    for key in DEFAULTS:
        conn.execute(
            sa.delete(system_config).where(system_config.c.key == key)
        )
