"""Database session management.

Connection pool tuned for Cloud Run + Cloud SQL micro (max 25 connections):
  pool_size=2: keep 2 idle connections per instance
  max_overflow=3: allow 3 extra under burst (5 total per instance)

  Safe ceiling: set Cloud Run max_instances=4 for Cloud SQL micro
    → 4 × 5 = 20 connections < 25 limit

  For Cloud SQL db-g1-small (1000 connections), max_instances=10+ is fine.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def _build_engine():
    url = settings.DATABASE_URL

    if url.startswith("sqlite:///:memory:") or url == "sqlite://":
        # In-memory SQLite for tests: StaticPool avoids cross-thread issues
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    if url.startswith("sqlite:"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
        )

    # MySQL / production
    return create_engine(
        url,
        pool_pre_ping=True,     # health-check connection before use
        pool_size=2,            # keep 2 idle connections per instance
        max_overflow=3,         # allow 3 extra under burst (5 total)
        pool_recycle=300,       # recycle after 5 min (MySQL wait_timeout safe)
        pool_timeout=30,        # fail fast if no connection available in 30s
    )


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


# FastAPI dependency — used with Depends(get_db)
def get_db() -> Generator[Session, None, None]:
    """Yield a DB session and guarantee it is closed after the request."""
    db = get_session_factory()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Context manager for non-FastAPI code (services, scripts, migrations)
@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager that yields a session and closes it on exit.

    Commits on clean exit, rolls back on exception, always closes.

    Usage:
        with db_session() as db:
            db.query(...)
    """
    db = get_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# For tests: override the engine with a test-specific one
def override_engine(test_engine) -> None:
    """Replace the global engine and session factory (for tests)."""
    global _engine, _SessionLocal
    _engine = test_engine
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def reset_engine() -> None:
    """Reset engine and session factory (for tests)."""
    global _engine, _SessionLocal
    if _engine:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


# ---------------------------------------------------------------------------
# Legacy aliases — kept so that existing imports don't break immediately.
# Callers should migrate to get_engine() / get_session_factory() / db_session().
# ---------------------------------------------------------------------------


def __getattr__(name: str):
    """Module-level __getattr__ for lazy `engine` and `SessionLocal` aliases."""
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_session_factory()
    raise AttributeError(f"module 'app.db.session' has no attribute {name!r}")
