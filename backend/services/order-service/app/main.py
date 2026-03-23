"""Order Service — FastAPI entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.handler.order_handler import router as order_router
from internal.handler.health_handler import router as health_router
from internal.model.order import Base
from internal.model.order_item import OrderItem  # noqa: F401

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://order_user:change_me_order@localhost:5435/order_db")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET", "dev_secret_gateway_key")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("order-service")

_engine_kwargs = {} if DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}

engine = create_async_engine(DATABASE_URL, echo=(ENVIRONMENT == "development"), **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Order Service starting up...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables ensured")
    yield
    await engine.dispose()
    logger.info("👋 Order Service shut down")


app = FastAPI(title="Order Service", description="Order lifecycle management", version="1.0.0", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)

from fastapi.responses import JSONResponse

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


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    async with async_session() as session:
        request.state.db = session
        response: Response = await call_next(request)
        return response


app.include_router(health_router)
app.include_router(order_router)


@app.get("/")
async def root():
    return {"service": "order-service", "version": "1.0.0"}
