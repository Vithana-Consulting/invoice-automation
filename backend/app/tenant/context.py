"""Tenant context using Python contextvars.

Holds the current company_id for the active request.
Thread-safe and async-safe — each request gets its own context.

Usage:
    TenantContext.set(company_id)   # Called by middleware at request start
    TenantContext.get()             # Used by repositories to filter queries
    TenantContext.clear()           # Called at request end
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

# The context variable — one value per async task / thread
_current_company_id: ContextVar[Optional[int]] = ContextVar(
    "current_company_id", default=None
)


class TenantContext:
    """Static accessor for the current tenant (company_id)."""

    @staticmethod
    def set(company_id: int) -> None:
        """Set the active company for this request."""
        _current_company_id.set(company_id)

    @staticmethod
    def get() -> int:
        """Get the active company_id. Raises if not set."""
        val = _current_company_id.get()
        if val is None:
            raise RuntimeError(
                "TenantContext not set. Ensure the request passes through "
                "the tenant middleware (get_tenant_context dependency)."
            )
        return val

    @staticmethod
    def get_optional() -> Optional[int]:
        """Get the active company_id, or None if not set."""
        return _current_company_id.get()

    @staticmethod
    def clear() -> None:
        """Clear the tenant context (called at request end)."""
        _current_company_id.set(None)
