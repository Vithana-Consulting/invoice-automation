from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db

router = APIRouter()


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "app": settings.APP_NAME,
        "database": db_status,
        "parser_mode": settings.PARSER_MODE,
        "llm_provider": settings.LLM_PROVIDER if settings.PARSER_MODE == "llm" else None,
        "llm_model": settings.LLM_MODEL if settings.PARSER_MODE == "llm" else None,
        "storage_backend": settings.STORAGE_BACKEND,
        "timestamp": datetime.utcnow().isoformat(),
    }
