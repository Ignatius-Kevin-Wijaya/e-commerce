"""Health check handler for product service."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "product-service"}


@router.get("/ready")
async def readiness_check(request: Request):
    try:
        db = request.state.db
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "service": "product-service", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "product-service", "error": str(e)}
        )
