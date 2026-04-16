"""Health handlers for carrier-mock-service."""

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "carrier-mock-service"}


@router.get("/ready")
async def readiness_check():
    return {"status": "ready", "service": "carrier-mock-service"}
