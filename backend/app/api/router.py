"""API router configuration.

Tenant context is set by TenantMiddleware (ASGI middleware) before
any route handler runs. Routes don't need explicit tenant dependencies.

Auth is still enforced per-route via get_current_user / get_optional_user.
"""
from fastapi import APIRouter

from app.api.health_routes import router as health_router
from app.api.auth_routes import router as auth_router
from app.api.draft_routes import router as draft_router
from app.api.rule_routes import router as rule_router
from app.api.vendor_mapping_routes import router as vendor_mapping_router
from app.api.integration_routes import router as integration_router
from app.api.ingest_routes import router as ingest_router
from app.api.dashboard_routes import router as dashboard_router
from app.api.admin_routes import router as admin_router
from app.api.settings_routes import router as settings_router
from app.api.coa_routes import router as coa_router
from app.api.bank_routes import router as bank_router
from app.api.payment_routes import router as payment_router

api_router = APIRouter()

# Public routes (no auth, no tenant)
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix="/api/auth", tags=["auth"])
api_router.include_router(admin_router, prefix="/api/admin", tags=["admin"])

# Tenant-scoped routes (tenant context set by middleware)
api_router.include_router(draft_router, prefix="/api/drafts", tags=["drafts"])
api_router.include_router(rule_router, prefix="/api/rules", tags=["rules"])
api_router.include_router(vendor_mapping_router, prefix="/api/vendor-mappings", tags=["vendor-mappings"])
api_router.include_router(integration_router, prefix="/api/integrations", tags=["integrations"])
api_router.include_router(ingest_router, prefix="/api/ingest", tags=["ingest"])
api_router.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
api_router.include_router(settings_router, prefix="/api/settings", tags=["settings"])
api_router.include_router(coa_router, prefix="/api/coa", tags=["chart-of-accounts"])
api_router.include_router(bank_router, prefix="/api/bank-details", tags=["bank-details"])
api_router.include_router(payment_router, prefix="/api", tags=["payments"])
