"""
Health check handler — Kubernetes liveness and readiness probes.

LEARNING NOTES:
- Kubernetes pings these endpoints to decide if your pod is healthy.
- /health (liveness): "Is the process alive?" If this fails, K8s RESTARTS the pod.
- /ready (readiness): "Can it handle traffic?" During thesis load tests we keep this
  lightweight/local so overload doesn't get misclassified as a dependency outage.
"""

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "auth-service"}


@router.get("/ready")
async def readiness_check():
    """Readiness probe — intentionally lightweight/local for experiment stability."""
    return {"status": "ready", "service": "auth-service", "check_mode": "lightweight-local"}
