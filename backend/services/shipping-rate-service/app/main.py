"""Shipping Rate Service — wait-dominant quote aggregation."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from internal.handler.health_handler import router as health_router
from internal.handler.shipping_handler import router as shipping_router

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET", "dev_secret_gateway_key")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("shipping-rate-service")

app = FastAPI(
    title="Shipping Rate Service",
    description="Aggregates shipping quotes from multiple carrier providers",
    version="1.0.0",
)
Instrumentator().instrument(app).expose(app)


@app.middleware("http")
async def verify_gateway_secret_middleware(request: Request, call_next):
    if request.url.path in ["/health", "/ready", "/docs", "/openapi.json", "/"] or request.url.path.startswith("/metrics"):
        return await call_next(request)

    secret = request.headers.get("x-internal-gateway-secret")
    if secret != INTERNAL_GATEWAY_SECRET:
        return JSONResponse(status_code=403, content={"detail": "Forbidden: Invalid Internal Gateway Secret"})

    return await call_next(request)


app.include_router(health_router)
app.include_router(shipping_router)


@app.get("/")
async def root():
    return {
        "service": "shipping-rate-service",
        "version": "1.0.0",
        "environment": ENVIRONMENT,
    }
