"""Cart Service — FastAPI entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from internal.cache.redis_client import close_redis
from internal.handler.cart_handler import router as cart_router
from internal.handler.health_handler import router as health_router

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
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

app.include_router(health_router)
app.include_router(cart_router)


@app.get("/")
async def root():
    return {"service": "cart-service", "version": "1.0.0"}
