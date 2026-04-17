"""Health handlers for shipping-rate-service."""

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    return {"status": "healthy", "service": "shipping-rate-service"}


@router.get("/ready")
def readiness_check():
    # Keep readiness local-only. A live carrier probe here caused the only
    # shipping pod to flap unready under B1 peak load even when the app itself
    # was still healthy enough to serve requests.
    return {
        "status": "ready",
        "service": "shipping-rate-service",
        "check_mode": "lightweight-local",
    }
