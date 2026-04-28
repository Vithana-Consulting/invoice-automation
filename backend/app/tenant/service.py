"""Company lifecycle management.

Handles company creation, user association, and view provisioning.
This is the single entry point for signup and company management.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from app.models.db_models import Company, CompanyMember, User
from app.tenant.views import create_company_views

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Convert company name to a URL-friendly slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:100] or "company"


class CompanyService:
    """Orchestrates company creation and membership management."""

    def __init__(self, db: Session):
        self.db = db

    def create_company(self, name: str, owner: User) -> Company:
        """Create a new company and assign the user as owner.

        Steps:
          1. Create Company record
          2. Create CompanyMember (user as owner)
          3. Create MySQL views for the company
        """
        # Generate unique slug
        base_slug = _slugify(name)
        slug = base_slug
        counter = 1
        while self.db.query(Company).filter(Company.slug == slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        company = Company(name=name, slug=slug)
        self.db.add(company)
        self.db.flush()  # Get the company.id

        # Link user as owner
        membership = CompanyMember(
            user_id=owner.id,
            company_id=company.id,
            role="owner",
        )
        self.db.add(membership)
        self.db.commit()

        # Create MySQL views for this company
        try:
            create_company_views(self.db, company.id)
        except Exception as e:
            # Views are non-critical — log and continue
            logger.warning("Failed to create views for company %d: %s", company.id, e)

        logger.info(
            "Company created: id=%d name='%s' slug='%s' owner=%d",
            company.id, name, slug, owner.id,
        )
        return company

    def add_member(self, company_id: int, user: User, role: str = "member") -> CompanyMember:
        """Add a user to a company."""
        existing = (
            self.db.query(CompanyMember)
            .filter(CompanyMember.user_id == user.id, CompanyMember.company_id == company_id)
            .first()
        )
        if existing:
            existing.is_active = True
            existing.role = role
            self.db.commit()
            return existing

        membership = CompanyMember(
            user_id=user.id,
            company_id=company_id,
            role=role,
        )
        self.db.add(membership)
        self.db.commit()
        return membership

    def get_user_companies(self, user_id: int) -> list:
        """Get all companies a user belongs to."""
        return (
            self.db.query(Company)
            .join(CompanyMember)
            .filter(CompanyMember.user_id == user_id, CompanyMember.is_active == True)
            .all()
        )

    def get_user_membership(self, user_id: int, company_id: int):
        """Get a user's membership in a specific company."""
        return (
            self.db.query(CompanyMember)
            .filter(
                CompanyMember.user_id == user_id,
                CompanyMember.company_id == company_id,
                CompanyMember.is_active == True,
            )
            .first()
        )
