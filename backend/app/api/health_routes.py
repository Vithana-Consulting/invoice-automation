from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/health")
def health_check(): # AI_RECOMMENDATION : update it with other metrices as well!
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "parser_mode": settings.PARSER_MODE,
    }
