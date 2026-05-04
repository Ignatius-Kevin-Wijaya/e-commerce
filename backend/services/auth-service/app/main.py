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
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.handler.auth_handler import router as auth_router
from internal.handler.health_handler import router as health_router
from internal.model.user import Base

# ── Configuration ─────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://auth_user:change_me_auth@localhost:5433/auth_db")
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
logger = logging.getLogger("auth-service")


def _should_skip_db_session(path: str) -> bool:
    """Keep liveness/docs/metrics outside the request DB session middleware."""
    return path in {"/health", "/ready", "/docs", "/openapi.json", "/"} or path.startswith("/metrics")

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
Instrumentator().instrument(app, latency_lowr_buckets=PROMETHEUS_LATENCY_BUCKETS).expose(app)

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


# ── Middleware: attach DB session to each request ─────────────
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Creates a fresh DB session per request and closes it after.
    The session is available as request.state.db in handlers.
    """
    if _should_skip_db_session(request.url.path):
        return await call_next(request)

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
