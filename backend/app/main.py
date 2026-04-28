import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.core.exceptions import AppError
from app.db.system_config import ConfigNotSetError
from app.tenant.repository import TenantNotSetError
from app.models.db_models import Base
from app.db.session import engine
from app.api.router import api_router

# Register all platform plugins (triggers @register_billing / @register_source)
import app.platforms.zoho  # noqa: F401
import app.platforms.stripe  # noqa: F401
import app.platforms.chargebee  # noqa: F401
import app.platforms.tally  # noqa: F401
import app.platforms.quickbooks  # noqa: F401
import app.platforms.gmail  # noqa: F401

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Schema managed by Alembic — run: alembic upgrade head
    # Fallback create_all for dev convenience (won't alter existing tables)
    logger.info("Checking database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Application started: %s", settings.APP_NAME)
    yield
    logger.info("Application shutting down.")


application = FastAPI(
    title=settings.APP_NAME,
    description="Vithana Accounting Automation Platform - Invoice Pipeline with Rule Builder",
    version="0.2.0",
    lifespan=lifespan,
)

# Middleware order matters — outermost first
# 1. CORS (outermost)
application.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Tenant context (sets company_id from JWT before route handlers)
from app.tenant.middleware import TenantMiddleware
application.add_middleware(TenantMiddleware)


@application.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Standardize all HTTP errors to {status, message} format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": str(exc.detail)},
    )


@application.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Standardize validation errors."""
    errors = [f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Validation failed", "errors": errors},
    )


@application.exception_handler(ConfigNotSetError)
async def config_not_set_handler(request: Request, exc: ConfigNotSetError):
    """Return 503 when required system config (OAuth, etc.) is not set."""
    return JSONResponse(
        status_code=503,
        content={"status": "error", "message": str(exc)},
    )


@application.exception_handler(TenantNotSetError)
async def tenant_not_set_handler(request: Request, exc: TenantNotSetError):
    """Return 401 when accessing tenant-scoped routes without authentication."""
    return JSONResponse(
        status_code=401,
        content={"status": "error", "message": "Not authenticated"},
    )


@application.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=400,
        content={"status": "error", "message": exc.message, "code": exc.code},
    )


@application.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"},
    )


application.include_router(api_router)


@application.get("/config")
def get_config():
    return {
        "status": "success",
        "data": {
            "app_name": settings.APP_NAME,
            "parser_mode": settings.PARSER_MODE,
            "gmail_label": settings.GMAIL_LABEL,
            "attachment_dir": settings.ATTACHMENT_DIR,
        },
    }
