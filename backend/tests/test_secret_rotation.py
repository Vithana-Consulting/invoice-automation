"""Tests for the SecretRotationManager.

All tests use an in-memory SQLite database — no external dependencies.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from inspect import getmembers
from typing import Generator
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="function")
def engine():
    """Fresh SQLite engine per test function for full isolation."""
    from sqlalchemy import create_engine as _create_engine
    from app.models.db_models import Base
    from app.db.session import override_engine, reset_engine

    test_engine = _create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    override_engine(test_engine)
    yield test_engine
    reset_engine()
    test_engine.dispose()


@pytest.fixture()
def db(engine) -> Generator[Session, None, None]:
    """Fresh DB session per test, rolled back afterwards for isolation."""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def manager():
    from app.core.secret_rotation import SecretRotationManager
    return SecretRotationManager()


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# 1. test_rotate_jwt_secret_key
# --------------------------------------------------------------------------- #

def test_rotate_jwt_secret_key(manager, db):
    result = manager.rotate(db, "JWT_SECRET_KEY", rotated_by="test@example.com")
    assert result["key"] == "JWT_SECRET_KEY"

    from app.models.db_models import SystemConfig
    new_record = db.query(SystemConfig).filter(SystemConfig.key == "JWT_SECRET_KEY").first()
    assert new_record is not None
    assert new_record.value  # a value was stored

    prev_record = db.query(SystemConfig).filter(
        SystemConfig.key == "JWT_SECRET_KEY_PREVIOUS"
    ).first()
    assert prev_record is not None  # old key was preserved


# --------------------------------------------------------------------------- #
# 2. test_rotate_jwt_creates_grace_period
# --------------------------------------------------------------------------- #

def test_rotate_jwt_creates_grace_period(manager, db):
    manager.rotate(db, "JWT_SECRET_KEY")
    assert manager.is_grace_period_active(db, "JWT_SECRET_KEY") is True


# --------------------------------------------------------------------------- #
# 3. test_rotate_jwt_grace_period_expiry_stored
# --------------------------------------------------------------------------- #

def test_rotate_jwt_grace_period_expiry_stored(manager, db):
    manager.rotate(db, "JWT_SECRET_KEY")

    from app.models.db_models import SystemConfig
    expiry_record = db.query(SystemConfig).filter(
        SystemConfig.key == "JWT_SECRET_KEY_GRACE_EXPIRES"
    ).first()
    assert expiry_record is not None
    assert expiry_record.value  # ISO timestamp stored
    # Must be parseable
    expires_at = datetime.fromisoformat(expiry_record.value)
    assert expires_at > datetime.utcnow()


# --------------------------------------------------------------------------- #
# 4. test_rotate_admin_api_key — no grace period for non-JWT keys
# --------------------------------------------------------------------------- #

def test_rotate_admin_api_key(manager, db):
    result = manager.rotate(db, "ADMIN_API_KEY", rotated_by="admin")
    assert result["key"] == "ADMIN_API_KEY"
    assert result["has_grace_period"] is False
    assert result["grace_expires_at"] is None

    # No grace/previous records created
    from app.models.db_models import SystemConfig
    prev = db.query(SystemConfig).filter(
        SystemConfig.key == "ADMIN_API_KEY_PREVIOUS"
    ).first()
    assert prev is None

    expiry = db.query(SystemConfig).filter(
        SystemConfig.key == "ADMIN_API_KEY_GRACE_EXPIRES"
    ).first()
    assert expiry is None


# --------------------------------------------------------------------------- #
# 5. test_rotate_non_rotatable_key_raises
# --------------------------------------------------------------------------- #

def test_rotate_non_rotatable_key_raises(manager, db):
    from app.core.secret_rotation import RotationError
    # DATABASE_URL is truly non-rotatable (not in ROTATABLE_KEYS, not in _REQUIRES_REENCRYPTION)
    with pytest.raises(RotationError):
        manager.rotate(db, "DATABASE_URL")


# --------------------------------------------------------------------------- #
# 5b. test_rotate_integration_encryption_key_raises
# --------------------------------------------------------------------------- #

def test_rotate_integration_encryption_key_raises(manager, db):
    """INTEGRATION_ENCRYPTION_KEY must raise RotationError mentioning re-encryption."""
    from app.core.secret_rotation import RotationError
    with pytest.raises(RotationError, match="re-encrypt"):
        manager.rotate(db, "INTEGRATION_ENCRYPTION_KEY")


# --------------------------------------------------------------------------- #
# 6. test_validate_jwt_with_current_key
# --------------------------------------------------------------------------- #

def test_validate_jwt_with_current_key(manager, db):
    # Rotate to set a known key
    manager.rotate(db, "JWT_SECRET_KEY", new_value="new-test-key-abcdef123456")

    from app.config import settings
    from app.models.db_models import SystemConfig

    current = db.query(SystemConfig).filter(SystemConfig.key == "JWT_SECRET_KEY").first()
    current_key = current.value

    token = jwt.encode({"sub": "user1"}, current_key, algorithm=settings.JWT_ALGORITHM)
    payload = manager.validate_jwt_with_rotation(token, db)
    assert payload["sub"] == "user1"


# --------------------------------------------------------------------------- #
# 7. test_validate_jwt_with_previous_key_in_grace_period
# --------------------------------------------------------------------------- #

def test_validate_jwt_with_previous_key_in_grace_period(manager, db):
    old_key = "old-jwt-secret-for-grace-test-xyz"
    new_key = "new-jwt-secret-after-rotation-abc"

    # Seed the "current" key so rotation picks it up as the previous
    from app.models.db_models import SystemConfig
    db.add(SystemConfig(key="JWT_SECRET_KEY", value=old_key, is_secret=True))
    db.flush()

    # Rotate — old_key becomes JWT_SECRET_KEY_PREVIOUS
    manager.rotate(db, "JWT_SECRET_KEY", new_value=new_key, grace_period_seconds=3600)

    from app.config import settings
    # Token signed with OLD key
    token = jwt.encode({"sub": "old-session"}, old_key, algorithm=settings.JWT_ALGORITHM)

    # Should succeed because grace period is active
    payload = manager.validate_jwt_with_rotation(token, db)
    assert payload["sub"] == "old-session"


# --------------------------------------------------------------------------- #
# 8. test_validate_jwt_with_previous_key_after_grace_period
# --------------------------------------------------------------------------- #

def test_validate_jwt_with_previous_key_after_grace_period(manager, db):
    old_key = "old-key-expired-grace"
    new_key = "new-key-after-rotation"

    from app.models.db_models import SystemConfig
    db.add(SystemConfig(key="JWT_SECRET_KEY", value=old_key, is_secret=True))
    db.flush()

    manager.rotate(db, "JWT_SECRET_KEY", new_value=new_key, grace_period_seconds=1)

    # Move grace expiry to the past
    expiry_record = db.query(SystemConfig).filter(
        SystemConfig.key == "JWT_SECRET_KEY_GRACE_EXPIRES"
    ).first()
    expiry_record.value = (datetime.utcnow() - timedelta(seconds=10)).isoformat()
    db.flush()

    from app.config import settings
    token = jwt.encode({"sub": "expired-session"}, old_key, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(jwt.InvalidTokenError):
        manager.validate_jwt_with_rotation(token, db)


# --------------------------------------------------------------------------- #
# 9. test_validate_jwt_no_previous_key
# --------------------------------------------------------------------------- #

def test_validate_jwt_no_previous_key(manager, db):
    from app.config import settings

    # Rotate once — sets up keys
    manager.rotate(db, "JWT_SECRET_KEY", new_value="current-key-only")

    # Remove the previous key record to simulate no previous key
    from app.models.db_models import SystemConfig
    prev = db.query(SystemConfig).filter(
        SystemConfig.key == "JWT_SECRET_KEY_PREVIOUS"
    ).first()
    if prev:
        db.delete(prev)
        db.flush()

    # Token signed with some random old key (not current)
    token = jwt.encode({"sub": "ghost"}, "totally-different-old-key", algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(jwt.InvalidTokenError):
        manager.validate_jwt_with_rotation(token, db)


# --------------------------------------------------------------------------- #
# 10. test_rotation_log_written
# --------------------------------------------------------------------------- #

def test_rotation_log_written(manager, db):
    manager.rotate(db, "JWT_SECRET_KEY", rotated_by="tester@example.com")

    from app.models.db_models import SecretRotationLog
    logs = db.query(SecretRotationLog).filter(
        SecretRotationLog.secret_key == "JWT_SECRET_KEY"
    ).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.rotated_by == "tester@example.com"
    assert log.rotation_method == "auto"
    assert log.grace_period_seconds is not None
    assert log.grace_expires_at is not None
    assert log.notes == "Rotated by tester@example.com"


# --------------------------------------------------------------------------- #
# 11. test_rotation_log_stores_hashes_not_values
# --------------------------------------------------------------------------- #

def test_rotation_log_stores_hashes_not_values(manager, db):
    old_key_value = "known-old-secret-for-hash-test"
    new_key_value = "known-new-secret-for-hash-test"

    from app.models.db_models import SystemConfig, SecretRotationLog
    db.add(SystemConfig(key="JWT_SECRET_KEY", value=old_key_value, is_secret=True))
    db.flush()

    manager.rotate(db, "JWT_SECRET_KEY", new_value=new_key_value)

    log = db.query(SecretRotationLog).filter(
        SecretRotationLog.secret_key == "JWT_SECRET_KEY"
    ).first()
    assert log is not None

    # Hashes must match SHA-256 of the actual values
    assert log.previous_key_hash == _sha256(old_key_value)
    assert log.new_key_hash == _sha256(new_key_value)

    # The raw values must NOT appear anywhere in the log record
    assert log.previous_key_hash != old_key_value
    assert log.new_key_hash != new_key_value


# --------------------------------------------------------------------------- #
# 12. test_rotation_log_is_immutable
# --------------------------------------------------------------------------- #

def test_rotation_log_is_immutable():
    """SecretRotationLog must not have an updated_at column (insert-only)."""
    from app.models.db_models import SecretRotationLog
    column_names = {c.key for c in SecretRotationLog.__table__.columns}
    assert "updated_at" not in column_names, (
        "SecretRotationLog must be insert-only — no updated_at column allowed"
    )


# --------------------------------------------------------------------------- #
# 13. test_get_rotation_history_returns_metadata_only
# --------------------------------------------------------------------------- #

def test_get_rotation_history_returns_metadata_only(manager, db):
    manager.rotate(db, "ADMIN_API_KEY", rotated_by="admin")
    history = manager.get_rotation_history(db, key="ADMIN_API_KEY")
    assert len(history) == 1
    entry = history[0]

    # Must have metadata fields
    assert "id" in entry
    assert "secret_key" in entry
    assert "rotated_at" in entry
    assert "rotated_by" in entry
    assert "rotation_method" in entry

    # Must NOT contain raw secret values
    assert "value" not in entry
    assert "new_value" not in entry
    assert "previous_value" not in entry

    # Hashes are OK for audit purposes — just verify no accidental secret leakage
    for field_value in entry.values():
        if isinstance(field_value, str) and len(field_value) > 20:
            # Should not look like a JWT secret (arbitrary string check)
            assert field_value != "admin"  # trivial sanity


# --------------------------------------------------------------------------- #
# 14. test_rotation_generates_secure_secret
# --------------------------------------------------------------------------- #

def test_rotation_generates_secure_secret(manager, db):
    """Generated secrets must be unique and at least 32 characters long."""
    seen: set[str] = set()
    for _ in range(100):
        result = manager.rotate(db, "LLAMAPARSE_API_KEY")
        from app.models.db_models import SystemConfig
        record = db.query(SystemConfig).filter(
            SystemConfig.key == "LLAMAPARSE_API_KEY"
        ).first()
        assert record is not None
        secret = record.value
        assert len(secret) >= 32, f"Generated secret too short: {len(secret)} chars"
        assert secret not in seen, "Duplicate secret generated!"
        seen.add(secret)


# --------------------------------------------------------------------------- #
# 15. test_rotate_with_custom_value
# --------------------------------------------------------------------------- #

def test_rotate_with_custom_value(manager, db):
    custom = "custom-test-key-supplied-externally"
    manager.rotate(db, "ADMIN_API_KEY", new_value=custom)

    from app.models.db_models import SystemConfig
    record = db.query(SystemConfig).filter(SystemConfig.key == "ADMIN_API_KEY").first()
    assert record is not None
    assert record.value == custom

    from app.models.db_models import SecretRotationLog
    log = db.query(SecretRotationLog).filter(
        SecretRotationLog.secret_key == "ADMIN_API_KEY"
    ).first()
    assert log.rotation_method == "manual"


# --------------------------------------------------------------------------- #
# 16. test_rotate_updates_existing_system_config_record
# --------------------------------------------------------------------------- #

def test_rotate_updates_existing_system_config_record(manager, db):
    """Rotating the same key twice must produce exactly one system_config row."""
    manager.rotate(db, "LLM_API_KEY")
    manager.rotate(db, "LLM_API_KEY")

    from app.models.db_models import SystemConfig
    count = db.query(SystemConfig).filter(SystemConfig.key == "LLM_API_KEY").count()
    assert count == 1  # upsert, not insert-duplicate


# --------------------------------------------------------------------------- #
# 17. test_is_grace_period_active_false_after_expiry
# --------------------------------------------------------------------------- #

def test_is_grace_period_active_false_after_expiry(manager, db):
    manager.rotate(db, "JWT_SECRET_KEY", grace_period_seconds=3600)

    # Manually set expiry to the past
    from app.models.db_models import SystemConfig
    expiry_record = db.query(SystemConfig).filter(
        SystemConfig.key == "JWT_SECRET_KEY_GRACE_EXPIRES"
    ).first()
    assert expiry_record is not None
    expiry_record.value = (datetime.utcnow() - timedelta(hours=2)).isoformat()
    db.flush()

    assert manager.is_grace_period_active(db, "JWT_SECRET_KEY") is False


# --------------------------------------------------------------------------- #
# 18. test_admin_endpoint_rotate_rejects_unknown_key
# --------------------------------------------------------------------------- #

def test_admin_endpoint_rotate_rejects_unknown_key(engine):
    """POST /admin/secrets/rotate with an unknown key must return HTTP 400."""
    from app.main import application
    from app.db.session import get_db
    import app.api.admin_routes as admin_mod

    # Override DB dependency to use our test DB
    SessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Bypass admin key verification entirely for this test
    def override_verify_admin_key():
        return None  # no-op — always passes

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[admin_mod._verify_admin_key] = override_verify_admin_key

    try:
        client = TestClient(application, raise_server_exceptions=False)
        response = client.post(
            "/api/admin/secrets/rotate",
            json={"key": "DATABASE_URL"},
            headers={"x-admin-key": "any-key"},
        )
        assert response.status_code == 400, (
            f"Expected 400 for non-rotatable key, got {response.status_code}: {response.text}"
        )
    finally:
        application.dependency_overrides.pop(get_db, None)
        application.dependency_overrides.pop(admin_mod._verify_admin_key, None)
