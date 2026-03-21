"""
Auth Service — FastAPI application entry point.

LEARNING NOTES:
- This is the main file that starts the FastAPI app.
- It wires together the database, routes, and middleware.
- The lifespan context manager handles startup/shutdown (create DB tables, close pool).
- A middleware attaches a DB session to every request so handlers can use it.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.handler.auth_handler import router as auth_router
from internal.handler.health_handler import router as health_router
from internal.model.user import Base

# ── Configuration ─────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://auth_user:change_me_auth@localhost:5433/auth_db")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("auth-service")

# ── Database engine (connection pool) ─────────────────────────
# SQLite doesn't support pool_size/max_overflow (it uses NullPool)
_engine_kwargs = {} if DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}

engine = create_async_engine(
    DATABASE_URL,
    echo=(ENVIRONMENT == "development"),
    **_engine_kwargs,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ── App lifespan (startup + shutdown) ─────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs on startup: create tables. Runs on shutdown: close DB pool."""
    logger.info("🚀 Auth Service starting up...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables ensured")
    yield
    await engine.dispose()
    logger.info("👋 Auth Service shut down")


# ── Create the FastAPI app ────────────────────────────────────
app = FastAPI(
    title="Auth Service",
    description="Handles user registration, login, JWT tokens, and sessions.",
    version="1.0.0",
    lifespan=lifespan,
)

# Prometheus metrics endpoint at /metrics
Instrumentator().instrument(app).expose(app)


# ── Middleware: attach DB session to each request ─────────────
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Creates a fresh DB session per request and closes it after.
    The session is available as request.state.db in handlers.
    """
    async with async_session() as session:
        request.state.db = session
        response: Response = await call_next(request)
        return response


# ── Register route handlers ──────────────────────────────────
app.include_router(health_router)
app.include_router(auth_router)


@app.get("/")
async def root():
    return {"service": "auth-service", "version": "1.0.0"}
