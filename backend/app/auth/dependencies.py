"""Authentication and tenant resolution dependencies.

Three dependency levels:
  1. get_current_user     — resolves JWT → User (global, no tenant)
  2. get_optional_user    — same but returns None on failure
  3. get_tenant_context   — resolves user → company, sets TenantContext

Most routes need (3) which chains through (1) automatically.
"""
from __future__ import annotations

import logging
from typing import Optional

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.models.db_models import Company, CompanyMember, User
from app.tenant.context import TenantContext

logger = logging.getLogger(__name__)


# ─── User Authentication ──────────────────────────────────────────────────


def get_current_user(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate JWT from cookie, return the User."""
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = jwt.decode(
            access_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def get_optional_user(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Same as get_current_user but returns None instead of raising."""
    if not access_token:
        return None
    try:
        return get_current_user(access_token=access_token, db=db)
    except HTTPException:
        return None


# ─── Tenant Resolution ────────────────────────────────────────────────────


def get_tenant_context(
    user: User = Depends(get_current_user),
    x_company_id: Optional[int] = Header(None),
    db: Session = Depends(get_db),
) -> int:
    """Resolve the active company for this request and set TenantContext.

    Priority:
      1. X-Company-Id header (if user is a member of that company)
      2. company_id from JWT payload
      3. User's first active company membership

    Returns the company_id. Also sets TenantContext for downstream repos.
    """
    if x_company_id:
        # Validate user is a member of the requested company
        membership = (
            db.query(CompanyMember)
            .filter(
                CompanyMember.user_id == user.id,
                CompanyMember.company_id == x_company_id,
                CompanyMember.is_active == True,
            )
            .first()
        )
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not a member of company {x_company_id}",
            )
        TenantContext.set(x_company_id)
        return x_company_id

    # Default: pick the user's first (or only) company
    membership = (
        db.query(CompanyMember)
        .filter(CompanyMember.user_id == user.id, CompanyMember.is_active == True)
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No company associated. Complete signup first.",
        )

    TenantContext.set(membership.company_id)
    logger.debug("TenantContext set: company_id=%d for user_id=%d", membership.company_id, user.id)
    return membership.company_id


def get_optional_tenant_context(
    user: Optional[User] = Depends(get_optional_user),
    x_company_id: Optional[int] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[int]:
    """Same as get_tenant_context but returns None if no auth."""
    if not user:
        return None
    try:
        return get_tenant_context(user=user, x_company_id=x_company_id, db=db)
    except HTTPException:
        return None
