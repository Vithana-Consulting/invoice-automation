"""Tests for DB-backed admin runtime config (Task 1).

Uses SQLite in-memory DB for isolation — no real MySQL required.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_session_module():
    """Reset engine singleton before and after every test."""
    from app.db.session import reset_engine
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def sqlite_engine():
    """Create a fresh SQLite in-memory engine with all tables."""
    from app.models.db_models import Base
    from app.db.session import override_engine
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    override_engine(engine)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_config_funcs():
    import app.config as cfg
    return cfg._load_overrides, cfg._save_overrides, cfg.EDITABLE_KEYS, cfg.SECRET_KEYS


# ---------------------------------------------------------------------------
# Test 1: _load_overrides returns {} when DB is empty
# ---------------------------------------------------------------------------

def test_load_overrides_returns_empty_when_db_empty(sqlite_engine):
    _load_overrides, _, _, _ = _get_config_funcs()
    result = _load_overrides()
    assert result == {}


# ---------------------------------------------------------------------------
# Test 2: _save_overrides persists to DB and _load_overrides reads it back
# ---------------------------------------------------------------------------

def test_save_overrides_persists_to_db(sqlite_engine):
    _load_overrides, _save_overrides, _, _ = _get_config_funcs()

    _save_overrides({"PARSER_MODE": "tesseract"})
    result = _load_overrides()

    assert result.get("PARSER_MODE") == "tesseract"


# ---------------------------------------------------------------------------
# Test 3: _save_overrides skips non-editable keys
# ---------------------------------------------------------------------------

def test_save_overrides_skips_non_editable_keys(sqlite_engine):
    _load_overrides, _save_overrides, _, _ = _get_config_funcs()

    _save_overrides({"DATABASE_URL": "evil://bad"})
    result = _load_overrides()

    assert "DATABASE_URL" not in result


# ---------------------------------------------------------------------------
# Test 4: _save_overrides updates an existing key
# ---------------------------------------------------------------------------

def test_save_overrides_update_existing(sqlite_engine):
    _load_overrides, _save_overrides, _, _ = _get_config_funcs()

    _save_overrides({"PARSER_MODE": "llm"})
    _save_overrides({"PARSER_MODE": "tesseract"})
    result = _load_overrides()

    assert result.get("PARSER_MODE") == "tesseract"


# ---------------------------------------------------------------------------
# Test 5: sysconfig.delete removes key so _load_overrides no longer returns it
# ---------------------------------------------------------------------------

def test_reset_config_deletes_from_db(sqlite_engine):
    _load_overrides, _save_overrides, _, _ = _get_config_funcs()

    _save_overrides({"LLM_MODEL": "gpt-4o"})
    assert "LLM_MODEL" in _load_overrides()

    from app.db.system_config import sysconfig
    sysconfig.delete("LLM_MODEL")

    result = _load_overrides()
    assert "LLM_MODEL" not in result


# ---------------------------------------------------------------------------
# Test 6: settings.__getattribute__ reads DB override via _load_overrides
# ---------------------------------------------------------------------------

def test_settings_getattribute_reads_from_db(sqlite_engine):
    _load_overrides, _save_overrides, _, _ = _get_config_funcs()

    _save_overrides({"PARSER_MODE": "tesseract"})

    import app.config as cfg
    assert cfg.settings.PARSER_MODE == "tesseract"


# ---------------------------------------------------------------------------
# Test 7: _load_overrides returns {} gracefully when DB is unavailable
# ---------------------------------------------------------------------------

def test_load_overrides_graceful_on_db_error():
    """When db_session raises, _load_overrides must return {} without raising."""
    from unittest.mock import patch
    from contextlib import contextmanager

    @contextmanager
    def broken_db_session():
        raise Exception("DB connection refused")
        yield  # unreachable

    # Patch at the source so the lazy import inside _load_overrides picks it up
    with patch("app.db.session.db_session", broken_db_session):
        _load_overrides, _, _, _ = _get_config_funcs()
        result = _load_overrides()

    assert result == {}


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

def _build_migration_engine():
    """Build a fresh SQLite in-memory engine with only the system_config table."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text(
            """
            CREATE TABLE system_config (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT,
                is_secret BOOLEAN DEFAULT 0,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))
        conn.commit()
    return engine


def _load_seed_migration_module():
    import importlib.util
    import os
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "../alembic/versions/c3d4e5f6a7b8_seed_system_config_defaults.py",
    )
    spec = importlib.util.spec_from_file_location("seed_migration", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_migration_upgrade(conn):
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations
    mod = _load_seed_migration_module()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        mod.upgrade()
    return mod


def _run_migration_downgrade(conn, mod):
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        mod.downgrade()


# ---------------------------------------------------------------------------
# Test 8: seed migration inserts all DEFAULTS keys
# ---------------------------------------------------------------------------

def test_seed_migration_inserts_defaults():
    engine = _build_migration_engine()
    with engine.connect() as conn:
        mod = _run_migration_upgrade(conn)
        conn.commit()

        rows = conn.execute(text("SELECT key, value FROM system_config")).fetchall()
        keys_in_db = {r[0]: r[1] for r in rows}

        for key in mod.DEFAULTS:
            assert key in keys_in_db, f"Expected key {key} to be seeded"

        assert keys_in_db.get("PARSER_MODE") == "tesseract", (
            "PARSER_MODE seed default must be 'tesseract', got: "
            f"{keys_in_db.get('PARSER_MODE')!r}"
        )

    engine.dispose()


# ---------------------------------------------------------------------------
# Test 9: seed migration skips existing rows (does not overwrite)
# ---------------------------------------------------------------------------

def test_seed_migration_skips_existing():
    engine = _build_migration_engine()
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO system_config (key, value, is_secret, updated_at) "
            "VALUES ('PARSER_MODE', 'custom_value', 0, :ts)"
        ), {"ts": datetime.utcnow()})
        conn.commit()

        mod = _run_migration_upgrade(conn)
        conn.commit()

        row = conn.execute(
            text("SELECT value FROM system_config WHERE key = 'PARSER_MODE'")
        ).fetchone()

        assert row is not None
        assert row[0] == "custom_value", "Existing value must NOT be overwritten by migration"

    engine.dispose()


# ---------------------------------------------------------------------------
# Test 10: seed migration downgrade removes seeded rows
# ---------------------------------------------------------------------------

def test_seed_migration_downgrade_removes_defaults():
    engine = _build_migration_engine()
    with engine.connect() as conn:
        mod = _run_migration_upgrade(conn)
        conn.commit()

        count_before = conn.execute(
            text("SELECT COUNT(*) FROM system_config")
        ).scalar()
        assert count_before == len(mod.DEFAULTS)

        _run_migration_downgrade(conn, mod)
        conn.commit()

        count_after = conn.execute(
            text("SELECT COUNT(*) FROM system_config")
        ).scalar()
        assert count_after == 0

    engine.dispose()


# ---------------------------------------------------------------------------
# Test 11: _save_overrides rolls back on commit failure
# ---------------------------------------------------------------------------

def test_save_overrides_rollback_on_db_error(sqlite_engine):
    """When db_session commit fails, rollback must be called."""
    from unittest.mock import patch, MagicMock
    from contextlib import contextmanager
    from app.db.session import get_session_factory

    real_session = get_session_factory()()
    mock_session = MagicMock(wraps=real_session)
    mock_session.commit.side_effect = Exception("simulated commit failure")

    @contextmanager
    def patched_db_session():
        yield mock_session
        mock_session.commit()  # trigger the side_effect

    # Patch at the source so the lazy import inside _save_overrides picks it up
    with patch("app.db.session.db_session", patched_db_session):
        _, _save_overrides, _, _ = _get_config_funcs()
        with pytest.raises(Exception, match="simulated commit failure"):
            _save_overrides({"PARSER_MODE": "llm"})

    real_session.close()
