"""Cart Service — FastAPI entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from internal.cache.redis_client import close_redis
from internal.handler.cart_handler import router as cart_router
from internal.handler.health_handler import router as health_router

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET", "dev_secret_gateway_key")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("cart-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Cart Service starting up...")
    yield
    await close_redis()
    logger.info("👋 Cart Service shut down")


app = FastAPI(title="Cart Service", description="Redis-backed shopping cart", version="1.0.0", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)

@app.middleware("http")
async def verify_gateway_secret_middleware(request: Request, call_next):
    """
    🔒 SECURITY: Critical #5 Protection against Header Spoofing
    Ensures that every request comes through the API Gateway by verifying the internal secret.
    """
    if request.url.path in ["/health", "/ready", "/docs", "/openapi.json", "/"] or request.url.path.startswith("/metrics"):
        return await call_next(request)
        
    secret = request.headers.get("x-internal-gateway-secret")
    if secret != INTERNAL_GATEWAY_SECRET:
        return JSONResponse(status_code=403, content={"detail": "Forbidden: Invalid Internal Gateway Secret"})
        
    return await call_next(request)

app.include_router(health_router)
app.include_router(cart_router)


@app.get("/")
async def root():
    return {"service": "cart-service", "version": "1.0.0"}
