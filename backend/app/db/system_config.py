"""System-level configuration stored in MySQL.

Replaces .env for runtime-configurable settings like OAuth credentials.
Provides a dict-like interface with get/set/delete.

Precedence: DB → .env → code default

Usage:
    from app.db.system_config import sysconfig

    # Read (checks DB first, falls back to .env/default)
    client_id = sysconfig.get("GOOGLE_CLIENT_ID")

    # Write (saves to DB)
    sysconfig.set("GOOGLE_CLIENT_ID", "1000.XXX")

    # Delete (reverts to .env/default)
    sysconfig.delete("GOOGLE_CLIENT_ID")

    # Bulk read
    all_oauth = sysconfig.get_many(["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"])
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConfigNotSetError(Exception):
    """Raised when a required system config key is not set in DB."""
    pass


# All admin-editable runtime settings managed via SystemConfig table
SYSTEM_KEYS = {
    "PARSER_MODE", "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL",
    "LLAMAPARSE_API_KEY",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
    "FRONTEND_URL", "DEBUG", "MAX_RETRIES",
}

# Keys that should be masked in API responses
SECRET_SYSTEM_KEYS = {"LLM_API_KEY", "LLAMAPARSE_API_KEY", "GOOGLE_CLIENT_SECRET"}


class SystemConfigManager:
    """Read/write system config from DB with .env fallback.

    Thread-safe: creates a new DB session per operation via db_session().
    """

    def get(self, key: str) -> str:
        """Get a config value from DB. Raises ConfigNotSetError if not configured."""
        from app.db.session import db_session
        from app.models.db_models import SystemConfig
        with db_session() as db:
            record = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if record and record.value is not None:
                return record.value
        raise ConfigNotSetError(
            f"{key} is not configured. Set it via Admin Dashboard → System Config."
        )

    def get_optional(self, key: str) -> Optional[str]:
        """Get a config value from DB, or None if not set."""
        try:
            return self.get(key)
        except ConfigNotSetError:
            return None

    def get_many(self, keys: List[str]) -> Dict[str, str]:
        """Get multiple config values from DB. Raises ConfigNotSetError if any key is missing."""
        from app.db.session import db_session
        from app.models.db_models import SystemConfig
        with db_session() as db:
            records = db.query(SystemConfig).filter(SystemConfig.key.in_(keys)).all()
            db_values = {r.key: r.value for r in records if r.value}

        missing = [k for k in keys if k not in db_values]
        if missing:
            raise ConfigNotSetError(
                f"Missing system config: {', '.join(missing)}. "
                "Set them via Admin Dashboard → System Config."
            )
        return db_values

    def set(self, key: str, value: str, is_secret: bool = None) -> None:
        """Set a config value in DB."""
        from app.db.session import db_session
        from app.models.db_models import SystemConfig
        with db_session() as db:
            record = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if record:
                record.value = value
                record.updated_at = datetime.utcnow()
                if is_secret is not None:
                    record.is_secret = is_secret
            else:
                db.add(SystemConfig(
                    key=key,
                    value=value,
                    is_secret=is_secret if is_secret is not None else key in SECRET_SYSTEM_KEYS,
                ))
        logger.info("SystemConfig updated: %s", key)

    def set_many(self, items: Dict[str, str]) -> None:
        """Set multiple config values at once."""
        for key, value in items.items():
            self.set(key, value)

    def delete(self, key: str) -> None:
        """Delete a config value (reverts to .env/default)."""
        from app.db.session import db_session
        from app.models.db_models import SystemConfig
        with db_session() as db:
            record = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if record:
                db.delete(record)
                logger.info("SystemConfig deleted: %s (reverted to .env)", key)

    def list_all(self) -> List[Dict[str, Any]]:
        """List all system config keys with their DB values."""
        from app.db.session import db_session
        from app.models.db_models import SystemConfig
        try:
            with db_session() as db:
                records = db.query(SystemConfig).all()
                db_values = {r.key: r for r in records}
        except Exception as exc:
            logger.warning("Failed to load system config list from DB: %s", exc)
            db_values = {}

        result = []
        for key in sorted(SYSTEM_KEYS):
            db_record = db_values.get(key)
            value = db_record.value if db_record and db_record.value else ""
            is_secret = key in SECRET_SYSTEM_KEYS
            is_set = bool(value)

            result.append({
                "key": key,
                "value": self._mask(value) if is_secret else value,
                "is_secret": is_secret,
                "is_set": is_set,
            })
        return result

    @staticmethod
    def _mask(value: str) -> str:
        if not value:
            return ""
        if len(value) > 8:
            return value[:4] + "****" + value[-4:]
        return "****"


# Singleton instance — import and use directly
sysconfig = SystemConfigManager()
