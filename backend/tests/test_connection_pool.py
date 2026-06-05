"""Tests for connection pool configuration and session lifecycle.

All tests use SQLite in-memory (via override_engine) so no real DB is needed.
Each test calls reset_engine() in teardown to prevent state leaks.
"""
from __future__ import annotations

import sys
import os

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sqlite_engine():
    """Return an in-memory SQLite engine suitable for tests."""
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _setup_tables(engine):
    """Create the SystemConfig table in the given engine."""
    from app.models.db_models import Base
    Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_session_module():
    """Reset global engine/session state before and after every test."""
    import app.db.session as session_mod
    session_mod.reset_engine()
    yield
    session_mod.reset_engine()


@pytest.fixture()
def sqlite_engine():
    eng = _make_sqlite_engine()
    _setup_tables(eng)
    return eng


@pytest.fixture()
def patched_engine(sqlite_engine):
    """Override the module engine with in-memory SQLite."""
    import app.db.session as session_mod
    session_mod.override_engine(sqlite_engine)
    return sqlite_engine


# ---------------------------------------------------------------------------
# get_db() tests
# ---------------------------------------------------------------------------

class TestGetDb:
    def test_get_db_yields_session(self, patched_engine):
        from app.db.session import get_db
        gen = get_db()
        db = next(gen)
        assert isinstance(db, Session)
        try:
            next(gen)
        except StopIteration:
            pass

    def test_get_db_closes_session_on_success(self, patched_engine):
        """Session must be closed after generator is exhausted normally."""
        from app.db.session import get_session_factory, get_db

        mock_session = MagicMock(spec=Session)
        factory = MagicMock(return_value=mock_session)

        with patch("app.db.session.get_session_factory", return_value=factory):
            gen = get_db()
            next(gen)
            try:
                next(gen)
            except StopIteration:
                pass

        mock_session.close.assert_called_once()

    def test_get_db_closes_session_on_exception(self, patched_engine):
        """Session must be closed AND rolled back when an exception propagates."""
        from app.db.session import get_db

        mock_session = MagicMock(spec=Session)
        factory = MagicMock(return_value=mock_session)

        with patch("app.db.session.get_session_factory", return_value=factory):
            gen = get_db()
            next(gen)
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("boom"))

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    def test_get_db_rollback_called_before_close_on_exception(self, patched_engine):
        """Verify rollback happens before close (order check via call_args_list)."""
        from app.db.session import get_db

        call_order = []
        mock_session = MagicMock(spec=Session)
        mock_session.rollback.side_effect = lambda: call_order.append("rollback")
        mock_session.close.side_effect = lambda: call_order.append("close")
        factory = MagicMock(return_value=mock_session)

        with patch("app.db.session.get_session_factory", return_value=factory):
            gen = get_db()
            next(gen)
            with pytest.raises(ValueError):
                gen.throw(ValueError("oops"))

        assert call_order == ["rollback", "close"]


# ---------------------------------------------------------------------------
# db_session() context manager tests
# ---------------------------------------------------------------------------

class TestDbSession:
    def test_db_session_context_manager_commits_on_success(self, patched_engine):
        """A successful block should commit the transaction."""
        from app.db.session import db_session
        from app.models.db_models import SystemConfig

        with db_session() as db:
            db.add(SystemConfig(key="TEST_KEY", value="hello"))

        # Read back in a fresh session; read value while session is still open
        # to avoid DetachedInstanceError after the context manager exits.
        found_value = None
        with db_session() as db:
            record = db.query(SystemConfig).filter(SystemConfig.key == "TEST_KEY").first()
            assert record is not None
            found_value = record.value
        assert found_value == "hello"

    def test_db_session_context_manager_rollback_on_exception(self, patched_engine):
        """An exception inside the block must roll back; row must NOT be committed."""
        from app.db.session import db_session
        from app.models.db_models import SystemConfig

        with pytest.raises(RuntimeError):
            with db_session() as db:
                db.add(SystemConfig(key="SHOULD_NOT_EXIST", value="x"))
                raise RuntimeError("abort")

        with db_session() as db:
            record = db.query(SystemConfig).filter(
                SystemConfig.key == "SHOULD_NOT_EXIST"
            ).first()
        assert record is None

    def test_db_session_always_closes(self, patched_engine):
        """close() must be called even when an exception is raised."""
        from app.db.session import get_session_factory, db_session

        mock_session = MagicMock(spec=Session)
        factory = MagicMock(return_value=mock_session)

        with patch("app.db.session.get_session_factory", return_value=factory):
            with pytest.raises(RuntimeError):
                with db_session() as db:
                    raise RuntimeError("crash")

        mock_session.close.assert_called_once()

    def test_db_session_rollback_called_on_exception(self, patched_engine):
        """rollback() must be called before close() on exception."""
        from app.db.session import db_session

        call_order = []
        mock_session = MagicMock(spec=Session)
        mock_session.rollback.side_effect = lambda: call_order.append("rollback")
        mock_session.close.side_effect = lambda: call_order.append("close")
        factory = MagicMock(return_value=mock_session)

        with patch("app.db.session.get_session_factory", return_value=factory):
            with pytest.raises(KeyError):
                with db_session():
                    raise KeyError("bad")

        assert call_order == ["rollback", "close"]


# ---------------------------------------------------------------------------
# Pool configuration tests
# ---------------------------------------------------------------------------

class TestPoolSettings:
    def test_pool_settings_for_mysql(self):
        """MySQL URL must produce a pool with an 18-connection ceiling and 10s timeout."""
        from app.db.session import _build_engine

        with patch("app.db.session.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            _build_engine.__wrapped__ = None  # clear any cache
            import app.db.session as session_mod
            # Temporarily patch the settings URL
            with patch.object(
                session_mod.settings, "DATABASE_URL",
                "mysql+pymysql://user:pass@localhost/testdb",
            ):
                session_mod._build_engine()

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs["pool_size"] == 6
        assert kwargs["max_overflow"] == 12
        # pool_size + max_overflow is the hard ceiling on connections
        assert kwargs["pool_size"] + kwargs["max_overflow"] == 18
        assert kwargs["pool_recycle"] == 300
        assert kwargs["pool_timeout"] == 10
        assert kwargs["pool_pre_ping"] is True

    def test_pool_settings_for_sqlite_memory(self):
        """sqlite:///:memory: must use StaticPool."""
        from app.db.session import _build_engine

        with patch("app.db.session.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            import app.db.session as session_mod
            with patch.object(
                session_mod.settings, "DATABASE_URL", "sqlite:///:memory:"
            ):
                session_mod._build_engine()

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs.get("poolclass") is StaticPool

    def test_pool_settings_for_sqlite_file(self):
        """File-based SQLite must use check_same_thread=False but NOT StaticPool."""
        from app.db.session import _build_engine

        with patch("app.db.session.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            import app.db.session as session_mod
            with patch.object(
                session_mod.settings, "DATABASE_URL", "sqlite:////tmp/test.db"
            ):
                session_mod._build_engine()

        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert kwargs.get("connect_args", {}).get("check_same_thread") is False
        assert "poolclass" not in kwargs


# ---------------------------------------------------------------------------
# override_engine / reset_engine tests
# ---------------------------------------------------------------------------

class TestEngineOverride:
    def test_override_engine_replaces_engine(self):
        """override_engine must make get_engine() return the test engine."""
        import app.db.session as session_mod

        fake_engine = MagicMock()
        session_mod.override_engine(fake_engine)
        assert session_mod.get_engine() is fake_engine

    def test_override_engine_replaces_session_factory(self):
        """override_engine must also reset the session factory to use the new engine."""
        import app.db.session as session_mod

        # Override, then verify we can still call get_session_factory without error
        fake_engine = _make_sqlite_engine()
        _setup_tables(fake_engine)
        session_mod.override_engine(fake_engine)
        factory = session_mod.get_session_factory()
        assert factory is not None
        # Factory should produce sessions bound to the new engine
        db = factory()
        assert db.bind is fake_engine
        db.close()

    def test_reset_engine_disposes_and_clears(self):
        """reset_engine must dispose the current engine and set _engine to None."""
        import app.db.session as session_mod

        fake_engine = MagicMock()
        session_mod._engine = fake_engine
        session_mod._SessionLocal = MagicMock()
        session_mod.reset_engine()

        fake_engine.dispose.assert_called_once()
        assert session_mod._engine is None
        assert session_mod._SessionLocal is None

    def test_reset_engine_when_no_engine(self):
        """reset_engine on a clean state must not raise."""
        import app.db.session as session_mod
        session_mod._engine = None
        session_mod._SessionLocal = None
        session_mod.reset_engine()  # must not raise


# ---------------------------------------------------------------------------
# SystemConfigManager session-lifecycle tests
# ---------------------------------------------------------------------------

class TestSystemConfigSessions:
    @pytest.fixture(autouse=True)
    def setup_sysconfig_engine(self, patched_engine):
        """All sysconfig tests run against in-memory SQLite."""
        pass

    def test_system_config_get_closes_session(self, patched_engine):
        """sysconfig.get() must close its session even when the key is absent."""
        from app.db.session import get_session_factory
        from app.db.system_config import sysconfig

        sessions_created: list[MagicMock] = []
        real_factory = get_session_factory()

        def tracking_factory():
            mock_sess = MagicMock(wraps=real_factory())
            sessions_created.append(mock_sess)
            return mock_sess

        mock_factory = MagicMock(side_effect=tracking_factory)

        with patch("app.db.session.get_session_factory", return_value=mock_factory):
            from app.db.system_config import ConfigNotSetError
            with pytest.raises(ConfigNotSetError):
                sysconfig.get("NONEXISTENT_KEY")

        for sess in sessions_created:
            sess.close.assert_called()

    def test_system_config_set_closes_session_on_success(self, patched_engine):
        """sysconfig.set() must close its session after a successful write."""
        from app.db.session import get_session_factory
        from app.db.system_config import sysconfig

        sessions_created: list[MagicMock] = []
        real_factory = get_session_factory()

        def tracking_factory():
            mock_sess = MagicMock(wraps=real_factory())
            sessions_created.append(mock_sess)
            return mock_sess

        mock_factory = MagicMock(side_effect=tracking_factory)

        with patch("app.db.session.get_session_factory", return_value=mock_factory):
            sysconfig.set("GOOGLE_CLIENT_ID", "test-value")

        for sess in sessions_created:
            sess.close.assert_called()

    def test_system_config_set_closes_session_on_db_error(self, patched_engine):
        """sysconfig.set() must close its session even when the DB raises.

        system_config.py does `from app.db.session import db_session` inside
        each method call, so we must patch it on the `app.db.session` module
        so that the fresh import picks up our mock.
        """
        from app.db.system_config import sysconfig

        mock_session = MagicMock(spec=Session)
        mock_session.query.side_effect = Exception("DB down")

        from contextlib import contextmanager

        @contextmanager
        def failing_db_session():
            try:
                yield mock_session
                mock_session.commit()
            except Exception:
                mock_session.rollback()
                raise
            finally:
                mock_session.close()

        # Patch on app.db.session so that the `from app.db.session import db_session`
        # inside system_config methods picks up our replacement.
        with patch("app.db.session.db_session", failing_db_session):
            with pytest.raises(Exception, match="DB down"):
                sysconfig.set("GOOGLE_CLIENT_ID", "fail")

        mock_session.close.assert_called_once()
        mock_session.rollback.assert_called_once()

    def test_system_config_get_returns_value_when_set(self, patched_engine):
        """Integration: set then get must round-trip correctly."""
        from app.db.system_config import sysconfig

        sysconfig.set("GOOGLE_CLIENT_ID", "my-client-id")
        value = sysconfig.get("GOOGLE_CLIENT_ID")
        assert value == "my-client-id"

    def test_system_config_delete_closes_session(self, patched_engine):
        """sysconfig.delete() must close its session."""
        from app.db.session import get_session_factory
        from app.db.system_config import sysconfig

        # First set a value
        sysconfig.set("GOOGLE_CLIENT_ID", "to-delete")

        sessions_created: list[MagicMock] = []
        real_factory = get_session_factory()

        def tracking_factory():
            mock_sess = MagicMock(wraps=real_factory())
            sessions_created.append(mock_sess)
            return mock_sess

        mock_factory = MagicMock(side_effect=tracking_factory)

        with patch("app.db.session.get_session_factory", return_value=mock_factory):
            sysconfig.delete("GOOGLE_CLIENT_ID")

        for sess in sessions_created:
            sess.close.assert_called()
