"""Multi-tenant isolation layer.

Architecture:
  - Single MySQL database, all tables have a `company_id` column
  - TenantContext (contextvars) holds the active company_id per request
  - TenantBaseRepository auto-filters all queries by company_id
  - MySQL views per company created on signup for reporting
"""
from app.tenant.context import TenantContext
from app.tenant.repository import TenantBaseRepository

__all__ = ["TenantContext", "TenantBaseRepository"]
