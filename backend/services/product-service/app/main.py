"""Product Service — FastAPI entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.handler.product_handler import router as product_router
from internal.handler.health_handler import router as health_router
from internal.limiter import limiter
from internal.model.category import Base  # Base is defined here
from internal.model.product import Product  # noqa: F401 — registers the Product table

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://product_user:change_me_product@localhost:5434/product_db")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET", "dev_secret_gateway_key")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("product-service")

_engine_kwargs = {} if DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}

engine = create_async_engine(DATABASE_URL, echo=(ENVIRONMENT == "development"), **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Product Service starting up...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables ensured")
    yield
    await engine.dispose()
    logger.info("👋 Product Service shut down")


app = FastAPI(title="Product Service", description="Product catalog and categories", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
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


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    async with async_session() as session:
        request.state.db = session
        response: Response = await call_next(request)
        return response


app.include_router(health_router)
app.include_router(product_router)


@app.get("/")
async def root():
    return {"service": "product-service", "version": "1.0.0"}
