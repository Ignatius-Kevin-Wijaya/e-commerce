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
PROMETHEUS_LATENCY_BUCKETS = (
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    1.5,
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    4.5,
    5.0,
    7.5,
    10.0,
    30.0,
    60.0,
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("shipping-rate-service")

app = FastAPI(
    title="Shipping Rate Service",
    description="Aggregates shipping quotes from multiple carrier providers",
    version="1.0.0",
)
# The default low-resolution histogram tops out at 1s, which clips the
# wait-dominant shipping workload during thesis experiments.
Instrumentator().instrument(app, latency_lowr_buckets=PROMETHEUS_LATENCY_BUCKETS).expose(app)


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
