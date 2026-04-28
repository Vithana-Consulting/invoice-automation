from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

RUNTIME_OVERRIDES_FILE = os.path.join("data", "runtime_config.json")

# Keys that are editable via admin dashboard at runtime
EDITABLE_KEYS = {
    "PARSER_MODE", "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL",
    "LLAMAPARSE_API_KEY",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
    "FRONTEND_URL", "DEBUG", "MAX_RETRIES",
}

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
    """Load runtime overrides from JSON file."""
    if os.path.exists(RUNTIME_OVERRIDES_FILE):
        try:
            with open(RUNTIME_OVERRIDES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_overrides(overrides: dict):
    """Save runtime overrides to JSON file."""
    os.makedirs(os.path.dirname(RUNTIME_OVERRIDES_FILE), exist_ok=True)
    with open(RUNTIME_OVERRIDES_FILE, "w") as f:
        json.dump(overrides, f, indent=2)


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

    # File storage
    ATTACHMENT_DIR: str = "data/attachments"

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
        # Only intercept known settings fields, not internal pydantic stuff
        if name.isupper() and not name.startswith("_"):
            overrides = _load_overrides()
            if name in overrides:
                return overrides[name]
        return super().__getattribute__(name)


settings = Settings()
