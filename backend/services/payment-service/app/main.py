"""Payment Service — FastAPI entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.handler.payment_handler import router as payment_router
from internal.handler.webhook_handler import router as webhook_router
from internal.model.payment import Base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://order_user:change_me_order@localhost:5435/order_db")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("payment-service")

_engine_kwargs = {} if DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}

engine = create_async_engine(DATABASE_URL, echo=(ENVIRONMENT == "development"), **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Payment Service starting up...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables ensured")
    yield
    await engine.dispose()
    logger.info("👋 Payment Service shut down")


app = FastAPI(title="Payment Service", description="Payment processing with Stripe simulation", version="1.0.0", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    async with async_session() as session:
        request.state.db = session
        response: Response = await call_next(request)
        return response


app.include_router(payment_router)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "payment-service"}


@app.get("/")
async def root():
    return {"service": "payment-service", "version": "1.0.0"}
