from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Keys that are editable via admin dashboard at runtime
EDITABLE_KEYS = {
    "PARSER_MODE", "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL",
    "LLAMAPARSE_API_KEY",
    "STORAGE_BACKEND",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
    "FRONTEND_URL", "DEBUG", "MAX_RETRIES",
}

# Valid values for enum-style settings
VALID_PARSER_MODES = {"tesseract", "llamaparse", "llm"}
VALID_STORAGE_BACKENDS = {"local", "google_drive"}

# Keys that should be masked in API responses (secrets)
SECRET_KEYS = {
    "LLM_API_KEY", "LLAMAPARSE_API_KEY", "GOOGLE_CLIENT_SECRET",
    "JWT_SECRET_KEY", "ADMIN_API_KEY", "INTEGRATION_ENCRYPTION_KEY",
    "ANTHROPIC_API_KEY",
}

# Keys that should NEVER be changed at runtime
READONLY_KEYS = {
    "DATABASE_URL", "ADMIN_API_KEY", "JWT_SECRET_KEY", "JWT_ALGORITHM",
}


def _load_overrides() -> dict:
    """Load runtime overrides from system_config DB table."""
    try:
        from app.db.session import db_session
        from app.models.db_models import SystemConfig
        with db_session() as db:
            records = db.query(SystemConfig).filter(
                SystemConfig.key.in_(EDITABLE_KEYS)
            ).all()
            return {r.key: r.value for r in records if r.value is not None}
    except Exception as exc:
        logger.warning("Failed to load runtime overrides from DB: %s", exc)
        return {}


def _save_overrides(overrides: dict) -> None:
    """Save runtime overrides to system_config DB table."""
    from app.db.session import db_session
    from app.models.db_models import SystemConfig
    with db_session() as db:
        for key, value in overrides.items():
            if key not in EDITABLE_KEYS:
                continue
            record = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if record:
                record.value = str(value)
                record.updated_at = datetime.utcnow()
            else:
                db.add(SystemConfig(
                    key=key,
                    value=str(value),
                    is_secret=key in SECRET_KEYS,
                ))
        # db_session() auto-commits on clean exit, rolls back on exception


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "vithana-accounting-platform"
    DEBUG: bool = False

    # Parser: tesseract | llamaparse | llm
    PARSER_MODE: str = "tesseract"

    # Database (MySQL via Docker, SQLite for local dev)
    DATABASE_URL: str = "mysql+pymysql://accounting:accounting@localhost:3306/accounting_automation"

    # Gmail (for invoice fetching - configured via Integrations UI in production)
    GMAIL_CREDENTIALS_FILE: str = "credentials.json"
    GMAIL_TOKEN_FILE: str = "token.json"
    GMAIL_LABEL: str = "invoices"
    GMAIL_SCOPES: str = "https://www.googleapis.com/auth/gmail.readonly"

    # LlamaParse (optional parser)
    LLAMAPARSE_API_KEY: str = ""

    # File storage: local | google_drive
    ATTACHMENT_DIR: str = "data/attachments"
    STORAGE_BACKEND: str = "local"

    # Retry
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: float = 2.0

    # Auth - Google OAuth for web login
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8001/api/auth/google/callback"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # LLM parser config (PARSER_MODE=llm)
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""

    # Legacy (kept for backward compat)
    ANTHROPIC_API_KEY: str = ""

    # Encryption key for integration secrets
    INTEGRATION_ENCRYPTION_KEY: str = ""

    # Admin key for destructive operations (flush all)
    ADMIN_API_KEY: str = ""

    # Frontend URL (for CORS and redirects)
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def __getattribute__(self, name: str) -> Any:
        """Override attribute access to check runtime overrides first."""
        # Only consult DB overrides for EDITABLE_KEYS — never for DATABASE_URL
        # or other bootstrap keys needed to build the DB connection itself.
        if name in EDITABLE_KEYS:
            overrides = _load_overrides()
            if name in overrides:
                return overrides[name]
        return super().__getattribute__(name)


settings = Settings()
