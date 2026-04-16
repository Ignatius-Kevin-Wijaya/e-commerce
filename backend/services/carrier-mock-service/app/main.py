"""Carrier Mock Service — deterministic delayed quote provider."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from internal.handler.carrier_handler import router as carrier_router
from internal.handler.health_handler import router as health_router

INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET", "dev_secret_gateway_key")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("carrier-mock-service")

app = FastAPI(
    title="Carrier Mock Service",
    description="Deterministic shipping carrier quote simulator",
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
app.include_router(carrier_router)


@app.get("/")
async def root():
    return {"service": "carrier-mock-service", "version": "1.0.0"}
