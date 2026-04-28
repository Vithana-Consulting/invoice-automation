"""Tenant-aware base repository.

All tenant-scoped repositories inherit from TenantBaseRepository.
This ensures every query is filtered by company_id, and every insert
is stamped with the correct company_id — no manual filtering needed.

Usage:
    class InvoiceRepository(TenantBaseRepository):
        model = InvoiceRecord

        def list_all(self):
            return self._base_query().order_by(...).all()

        def create(self, **kwargs):
            record = InvoiceRecord(**kwargs)
            return self._create(record)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Type

from sqlalchemy.orm import Session

from app.tenant.context import TenantContext


class TenantNotSetError(Exception):
    """Raised when a tenant-scoped repo is created without TenantContext."""
    pass


class TenantBaseRepository:
    """Base class for all tenant-scoped repositories.

    Subclasses MUST set `model` to their SQLAlchemy model class.
    All queries automatically filter by the current tenant's company_id.
    """

    model: Type = None  # Override in subclasses

    def __init__(self, db: Session):
        self.db = db
        company_id = TenantContext.get_optional()
        if company_id is None:
            raise TenantNotSetError("Authentication required")
        self._company_id = company_id

    @property
    def company_id(self) -> int:
        """The active tenant's company_id."""
        return self._company_id

    def _base_query(self):
        """Start a query pre-filtered by company_id.

        All repository query methods should start with this
        instead of self.db.query(self.model) directly.
        """
        return self.db.query(self.model).filter(
            self.model.company_id == self._company_id
        )

    def _stamp(self, record):
        """Stamp company_id onto a new record before insert.

        Call this before db.add() to ensure tenant isolation.
        """
        record.company_id = self._company_id
        return record

    def _create(self, record):
        """Stamp, add, commit, and refresh a new record."""
        self._stamp(record)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def _get_by_id(self, record_id: int):
        """Get a record by ID, scoped to the current tenant."""
        return self._base_query().filter(self.model.id == record_id).first()

    def _update(self, record_id: int, **kwargs):
        """Update a record by ID, scoped to the current tenant."""
        record = self._get_by_id(record_id)
        if not record:
            return None
        for key, value in kwargs.items():
            if hasattr(record, key):
                setattr(record, key, value)
        if hasattr(record, "updated_at"):
            record.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(record)
        return record

    def _delete(self, record_id: int) -> bool:
        """Delete a record by ID, scoped to the current tenant."""
        record = self._get_by_id(record_id)
        if not record:
            return False
        self.db.delete(record)
        self.db.commit()
        return True
