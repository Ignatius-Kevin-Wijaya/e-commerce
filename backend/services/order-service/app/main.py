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
