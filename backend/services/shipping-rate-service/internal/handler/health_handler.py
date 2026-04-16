"""Health handlers for shipping-rate-service."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from internal.client.carrier_client import CarrierClient

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "shipping-rate-service"}


@router.get("/ready")
async def readiness_check():
    try:
        carrier_state = await CarrierClient().health_check()
        return {
            "status": "ready",
            "service": "shipping-rate-service",
            "carrier_dependency": carrier_state.get("service", "carrier-mock-service"),
        }
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "shipping-rate-service", "error": str(exc)},
        )
