"""Secret Rotation Manager for Vithana Accounting Platform.

Handles cryptographically secure rotation of platform secrets with:
- Immutable audit log (SecretRotationLog)
- JWT grace period support (old + new key both valid during transition)
- SHA-256 hashes in audit trail (never raw secret values)
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt

from app.config import SECRET_KEYS, settings
from app.models.db_models import SecretRotationLog, SystemConfig

# Keys the rotation manager can rotate
ROTATABLE_KEYS = {
    "JWT_SECRET_KEY",
    "ADMIN_API_KEY",
    "LLM_API_KEY",
    "LLAMAPARSE_API_KEY",
    # INTEGRATION_ENCRYPTION_KEY is intentionally excluded:
    # rotating it requires re-encrypting all Integration.config_encrypted blobs first.
    # Use the dedicated re-encryption migration script when this is needed.
}

# Keys that require pre-rotation migration work before they can be safely rotated
_REQUIRES_REENCRYPTION = {"INTEGRATION_ENCRYPTION_KEY"}

# Keys that need a grace period (active tokens/sessions must remain valid)
GRACE_PERIOD_KEYS = {"JWT_SECRET_KEY"}
DEFAULT_JWT_GRACE_SECONDS = 3600  # 1 hour


class RotationError(Exception):
    pass


class SecretRotationManager:
    """Manages secret rotation with audit trail and JWT grace period support.

    Design principles:
    - Never stores secrets in instance memory — reads from DB on every call
    - Audit log is insert-only (SecretRotationLog has no updated_at)
    - Only SHA-256 hashes appear in logs, never plaintext secret values
    """

    def _generate_secret(self, key: str) -> str:
        """Generate a cryptographically secure secret appropriate for the key type."""
        if key in ("JWT_SECRET_KEY", "INTEGRATION_ENCRYPTION_KEY"):
            return secrets.token_hex(32)  # 256-bit hex
        if key == "ADMIN_API_KEY":
            return secrets.token_urlsafe(24)  # 32-char URL-safe base64
        return secrets.token_urlsafe(32)  # generic: 43-char URL-safe

    def _sha256(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def rotate(
        self,
        db,
        key: str,
        rotated_by: str = "system",
        grace_period_seconds: Optional[int] = None,
        new_value: Optional[str] = None,
    ) -> dict:
        """Rotate a secret key.

        Steps:
        1. Validate the key is rotatable
        2. Read the current value (from system_config or settings fallback)
        3. Generate (or accept) new value
        4. If JWT_SECRET_KEY: save old value as JWT_SECRET_KEY_PREVIOUS with expiry
        5. Save new value to system_config
        6. Write to secret_rotation_log (immutable)
        7. Return rotation metadata (no secrets in return value)
        """
        if key in _REQUIRES_REENCRYPTION:
            raise RotationError(
                f"Rotating '{key}' requires re-encrypting all tenant integration secrets first. "
                "Run the re-encryption migration script before rotating this key."
            )
        if key not in ROTATABLE_KEYS:
            raise RotationError(f"Key '{key}' is not in ROTATABLE_KEYS: {ROTATABLE_KEYS}")

        # Get current value — never stored in memory beyond this scope
        current_record = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        current_value: str = current_record.value if current_record else getattr(settings, key, "")

        # Generate new value
        new_secret = new_value if new_value is not None else self._generate_secret(key)

        # Handle grace period for JWT
        grace_expires_at: Optional[datetime] = None
        if key in GRACE_PERIOD_KEYS:
            grace_secs = grace_period_seconds if grace_period_seconds is not None else DEFAULT_JWT_GRACE_SECONDS
            grace_expires_at = datetime.utcnow() + timedelta(seconds=grace_secs)

            # Store old key as fallback for grace period
            prev_key_name = f"{key}_PREVIOUS"
            prev_record = db.query(SystemConfig).filter(SystemConfig.key == prev_key_name).first()
            if prev_record:
                prev_record.value = current_value or ""
                prev_record.updated_at = datetime.utcnow()
            else:
                db.add(SystemConfig(key=prev_key_name, value=current_value or "", is_secret=True))

            # Store grace expiry timestamp
            expiry_key = f"{key}_GRACE_EXPIRES"
            expiry_record = db.query(SystemConfig).filter(SystemConfig.key == expiry_key).first()
            expiry_val = grace_expires_at.isoformat()
            if expiry_record:
                expiry_record.value = expiry_val
                expiry_record.updated_at = datetime.utcnow()
            else:
                db.add(SystemConfig(key=expiry_key, value=expiry_val, is_secret=False))

        # Update/insert new secret
        if current_record:
            current_record.value = new_secret
            current_record.updated_at = datetime.utcnow()
        else:
            db.add(SystemConfig(key=key, value=new_secret, is_secret=True))

        # Write audit log (immutable — no updates ever)
        log_entry = SecretRotationLog(
            secret_key=key,
            rotated_by=rotated_by,
            rotation_method="manual" if new_value is not None else "auto",
            previous_key_hash=self._sha256(current_value) if current_value else None,
            new_key_hash=self._sha256(new_secret),
            grace_period_seconds=(
                grace_period_seconds
                if grace_period_seconds is not None
                else (DEFAULT_JWT_GRACE_SECONDS if key in GRACE_PERIOD_KEYS else None)
            ),
            grace_expires_at=grace_expires_at,
            notes=f"Rotated by {rotated_by}",
        )
        db.add(log_entry)
        db.commit()

        return {
            "key": key,
            "rotated_at": log_entry.rotated_at.isoformat(),
            "rotated_by": rotated_by,
            "grace_expires_at": grace_expires_at.isoformat() if grace_expires_at else None,
            "has_grace_period": key in GRACE_PERIOD_KEYS,
        }

    def validate_jwt_with_rotation(self, token: str, db) -> dict:
        """Decode a JWT trying current key first, then previous key if in grace period.

        Returns the decoded payload or raises jwt.InvalidTokenError.
        Never stores keys in instance state between calls.
        """
        # Try current key first — always read from DB
        current = db.query(SystemConfig).filter(SystemConfig.key == "JWT_SECRET_KEY").first()
        current_key = current.value if current else settings.JWT_SECRET_KEY

        try:
            return jwt.decode(token, current_key, algorithms=[settings.JWT_ALGORITHM])
        except jwt.InvalidTokenError:
            pass

        # Try previous key if grace period is active
        prev = db.query(SystemConfig).filter(SystemConfig.key == "JWT_SECRET_KEY_PREVIOUS").first()
        expiry = db.query(SystemConfig).filter(SystemConfig.key == "JWT_SECRET_KEY_GRACE_EXPIRES").first()

        if not prev or not prev.value or not expiry or not expiry.value:
            raise jwt.InvalidTokenError("Token invalid and no grace period active")

        try:
            expires_at = datetime.fromisoformat(expiry.value)
        except ValueError:
            raise jwt.InvalidTokenError("Invalid grace expiry timestamp")

        if datetime.utcnow() > expires_at:
            raise jwt.InvalidTokenError("Token invalid and grace period has expired")

        # Grace period still active — try previous key
        return jwt.decode(token, prev.value, algorithms=[settings.JWT_ALGORITHM])

    def get_rotation_history(self, db, key: Optional[str] = None, limit: int = 50) -> list:
        """Get rotation history for audit purposes. Returns metadata only, no secret values."""
        query = db.query(SecretRotationLog)
        if key:
            query = query.filter(SecretRotationLog.secret_key == key)
        records = query.order_by(SecretRotationLog.rotated_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "secret_key": r.secret_key,
                "rotated_at": r.rotated_at.isoformat(),
                "rotated_by": r.rotated_by,
                "rotation_method": r.rotation_method,
                "grace_period_seconds": r.grace_period_seconds,
                "grace_expires_at": r.grace_expires_at.isoformat() if r.grace_expires_at else None,
                "notes": r.notes,
            }
            for r in records
        ]

    def is_grace_period_active(self, db, key: str) -> bool:
        """Check if a grace period is currently active for a key."""
        expiry_key = f"{key}_GRACE_EXPIRES"
        expiry = db.query(SystemConfig).filter(SystemConfig.key == expiry_key).first()
        if not expiry or not expiry.value:
            return False
        try:
            return datetime.utcnow() < datetime.fromisoformat(expiry.value)
        except ValueError:
            return False


# Module-level singleton — stateless, safe to share across threads
rotation_manager = SecretRotationManager()
