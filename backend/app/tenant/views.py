"""MySQL view management for multi-tenant reporting.

On company signup, we create one view per tenant-scoped table.
Views provide a clean SQL interface for reporting tools, admin dashboards,
and direct DB access — all pre-filtered by company_id.

Example: company_id=5 gets views like:
    v_company_5_invoices
    v_company_5_invoice_drafts
    v_company_5_rules
    ...
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Tables that are tenant-scoped (have company_id column)
TENANT_TABLES = [
    "invoices",
    "invoice_drafts",
    "rules",
    "vendor_mappings",
    "integrations",
    "platform_vendors",
    "processed_emails",
    "vendor_cache",
    "audit_log",
]


def create_company_views(db: Session, company_id: int) -> None:
    """Create MySQL views for a company. Called once on signup.

    Each view is a SELECT * WHERE company_id = N, giving the company
    an isolated view of their data without separate databases.
    """
    for table in TENANT_TABLES:
        view_name = f"v_company_{company_id}_{table}"
        # Use string formatting for DDL (parameterized queries don't work for identifiers) # AI_TECH_EXPLAIN : explain this ?  string formatting for DDL (parameterized queries don't work for identifiers)  and y paramterised queries wont work?
        sql = f"CREATE OR REPLACE VIEW `{view_name}` AS SELECT * FROM `{table}` WHERE company_id = {company_id}"
        db.execute(text(sql))

    db.commit()
    logger.info("Created %d views for company_id=%d", len(TENANT_TABLES), company_id)


def drop_company_views(db: Session, company_id: int) -> None:
    """Drop all views for a company. Called on company deletion."""
    for table in TENANT_TABLES:
        view_name = f"v_company_{company_id}_{table}"
        db.execute(text(f"DROP VIEW IF EXISTS `{view_name}`"))

    db.commit()
    logger.info("Dropped views for company_id=%d", company_id)
