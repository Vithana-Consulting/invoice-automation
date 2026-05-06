"""ASGI middleware to set TenantContext for every authenticated request.

Runs before any route handler. Extracts JWT from cookie,
resolves user → company membership, and sets TenantContext.

Non-authenticated requests (health, auth, admin) pass through
with TenantContext unset — those routes don't use tenant repos.
"""
from __future__ import annotations

import logging

import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.db.session import db_session
from app.models.db_models import CompanyMember, User
from app.tenant.context import TenantContext

logger = logging.getLogger(__name__)

# Paths that don't need tenant context
SKIP_PATHS = {
    "/health", "/config", "/docs", "/openapi.json", "/redoc",
}
SKIP_PREFIXES = ("/api/auth/", "/api/admin/")


class TenantMiddleware(BaseHTTPMiddleware):
    """Sets TenantContext from JWT cookie for every authenticated request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always clear context at start
        TenantContext.clear()

        path = request.url.path

        # Skip public/auth/admin paths
        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        # Extract JWT from cookie
        token = request.cookies.get("access_token")
        if not token:
            return await call_next(request)

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            user_id = payload.get("sub")
            if not user_id:
                return await call_next(request)

            # Look up company membership
            with db_session() as db:
                # Check for X-Company-Id header
                company_id_header = request.headers.get("x-company-id")

                if company_id_header:
                    try:
                        cid = int(company_id_header)
                    except ValueError:
                        return await call_next(request)
                    membership = (
                        db.query(CompanyMember)
                        .filter(
                            CompanyMember.user_id == int(user_id),
                            CompanyMember.company_id == cid,
                            CompanyMember.is_active == True,
                        )
                        .first()
                    )
                else:
                    membership = (
                        db.query(CompanyMember)
                        .filter(
                            CompanyMember.user_id == int(user_id),
                            CompanyMember.is_active == True,
                        )
                        .first()
                    )

                if membership:
                    TenantContext.set(membership.company_id)

        except (jwt.InvalidTokenError, ValueError):
            pass  # Invalid token — let the auth dependency handle the 401

        try:
            response = await call_next(request)
        finally:
            TenantContext.clear()

        return response
