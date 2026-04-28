"""Authentication routes — per-tenant Google OAuth login.

Flow:
  1. User enters email on login page
  2. POST /api/auth/login {email} → lookup company by domain → return OAuth URL
  3. User redirected to Google → authenticates → callback
  4. GET /api/auth/google/callback → decode state (company_id) → create user → JWT
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.oauth import (
    create_jwt_token,
    exchange_code_for_tokens,
    get_google_auth_url,
    get_google_user_info,
    verify_oauth_state,
)
from app.config import settings
from app.db.repository import UserRepository
from app.db.session import get_db
from app.models.db_models import Company, CompanyMember, Integration, User
from app.tenant.service import CompanyService

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    company_slug: str


# ─── Public company list (for login dropdown) ────────────────────────────


@router.get("/companies")
async def list_companies_public(db: Session = Depends(get_db)):
    """Return list of active companies with OAuth configured (for login dropdown)."""
    companies = (
        db.query(Company)
        .filter(Company.is_active == True)
        .order_by(Company.name)
        .all()
    )
    # Check which companies have OAuth configured
    oauth_company_ids = {
        row.company_id
        for row in db.query(Integration.company_id).filter(Integration.platform == "google_oauth").all()
    } # AI_RECOMMENDATION : Search option is recommended and if in case there are 10k companies, it can fetch all right? so search option has to be implemented
    return {
        "status": "success",
        "data": [
            {"slug": c.slug, "name": c.name, "oauth_configured": c.id in oauth_company_ids}
            for c in companies
        ],
    }


# ─── Company-based login ─────────────────────────────────────────────────


@router.post("/login")
async def login_by_company(body: LoginRequest, db: Session = Depends(get_db)):
    """Lookup company by slug, return Google OAuth URL.

    Frontend sends selected company slug → backend finds the company → returns OAuth redirect URL.
    """
    slug = body.company_slug.strip().lower() # AI_RECOMMENDATION : domain validation thread is already listed there in the admin_routes.py,thinking of alternate way to handle this

    company = db.query(Company).filter(Company.slug == slug, Company.is_active == True).first()
    if not company:
        raise HTTPException(
            status_code=404,
            detail=f"No company found with slug '{slug}'. Contact your administrator.",
        )

    # Build OAuth URL for this company
    try:
        auth_url = get_google_auth_url(company.id, db)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {"status": "success", "data": {"redirect_url": auth_url, "company": company.name}}


@router.get("/google/login")
async def google_login_legacy():
    """Legacy endpoint — directs users to the email-first flow."""
    raise HTTPException(
        status_code=400,
        detail="Use POST /api/auth/login with {email} instead. Each company has its own OAuth.",
    )


# ─── OAuth callback ───────────────────────────────────────────────────────


@router.get("/google/callback")
async def google_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    """Handle Google OAuth callback.

    Decodes company_id from signed state parameter,
    exchanges code for tokens using that company's credentials,
    creates/updates user, links to company, and issues JWT.
    """
    # Verify state → get company_id
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")
    try:
        company_id = verify_oauth_state(state)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    # Verify company exists
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=400, detail="Company not found")

    # Exchange code for tokens using this company's OAuth credentials
    try:
        tokens = await exchange_code_for_tokens(company_id, code, db)
    except Exception as e:
        logger.error("Token exchange failed for company %d: %s", company_id, e)
        raise HTTPException(status_code=400, detail=f"OAuth token exchange failed: {type(e).__name__}")

    access_token = tokens["access_token"]
    user_info = await get_google_user_info(access_token)
    google_sub = user_info["sub"]
    email = user_info.get("email", "")
    name = user_info.get("name", "")
    picture = user_info.get("picture", "")

    # Upsert user
    user_repo = UserRepository(db)
    user = user_repo.create_or_update(google_sub, email, name, picture)

    # Ensure user is a member of this company
    membership = (
        db.query(CompanyMember)
        .filter(CompanyMember.user_id == user.id, CompanyMember.company_id == company_id)
        .first()
    )
    if not membership:
        membership = CompanyMember(user_id=user.id, company_id=company_id, role="member")
        db.add(membership)
        db.commit()
        logger.info("User %s added to company %d (%s)", email, company_id, company.name)

    jwt_token = create_jwt_token(user.id)

    response = RedirectResponse(url=settings.FRONTEND_URL + "/dashboard")
    response.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        secure=False,  # Set True in production with HTTPS
        samesite="lax",
        max_age=settings.JWT_EXPIRATION_HOURS * 3600,
    )
    return response


# ─── Session management ───────────────────────────────────────────────────


@router.post("/logout")
async def logout(response: Response):
    """Clear JWT cookie."""
    response.delete_cookie("access_token")
    return {"status": "success", "message": "Logged out"}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return current authenticated user with company info."""
    memberships = (
        db.query(CompanyMember)
        .filter(CompanyMember.user_id == user.id, CompanyMember.is_active == True)
        .all()
    )
    companies = [
        {
            "id": m.company_id,
            "name": m.company.name if m.company else "",
            "slug": m.company.slug if m.company else "",
            "domain": m.company.domain if m.company else "",
            "role": m.role,
        }
        for m in memberships
    ]
    return {
        "status": "success",
        "data": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture_url": user.picture_url,
            "is_admin": user.is_admin,
            "companies": companies,
            "active_company": companies[0] if companies else None,
        },
    }
