"""Health check handler for cart service."""

from fastapi import APIRouter
from internal.cache.redis_client import get_redis

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "cart-service"}


@router.get("/ready")
async def readiness_check():
    try:
        r = await get_redis()
        await r.ping()
        return {"status": "ready", "service": "cart-service", "redis": "connected"}
    except Exception as e:
        return {"status": "not_ready", "service": "cart-service", "error": str(e)}
