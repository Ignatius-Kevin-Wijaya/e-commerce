"""
Health check handler — Kubernetes liveness and readiness probes.

LEARNING NOTES:
- Kubernetes pings these endpoints to decide if your pod is healthy.
- /health (liveness): "Is the process alive?" If this fails, K8s RESTARTS the pod.
- /ready (readiness): "Can it handle traffic?" If this fails, K8s stops sending requests
  but does NOT restart — useful during startup or when the DB is down.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "auth-service"}


@router.get("/ready")
async def readiness_check(request: Request):
    """Readiness probe — checks database connectivity."""
    try:
        db = request.state.db
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "service": "auth-service", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "auth-service", "error": str(e)}
        )
