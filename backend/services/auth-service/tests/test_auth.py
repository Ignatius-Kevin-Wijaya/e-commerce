"""
Auth Service tests.

LEARNING NOTES:
- We test the service layer directly (unit tests) and HTTP endpoints (integration tests).
- We use an in-memory SQLite database for fast, isolated tests.
- pytest-asyncio lets us write async test functions.
- httpx.AsyncClient lets us call FastAPI routes without starting a real server.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.model.user import Base

# ── Test database setup ──────────────────────────────────────
# Note: For CI, we use SQLite. For local dev with Docker, we use Postgres.
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_auth.db"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create tables before each test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Create a test HTTP client with test DB overrides."""
    from app.main import app
    from internal.handler.auth_handler import get_auth_service
    from internal.repository.user_repository import UserRepository
    from internal.service.auth_service import AuthService

    async def override_get_auth_service():
        async with TestSession() as session:
            repo = UserRepository(session)
            yield AuthService(repo)

    app.dependency_overrides[get_auth_service] = override_get_auth_service
    transport = ASGITransport(app=app)
    headers = {"X-Internal-Gateway-Secret": "dev_secret_gateway_key"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Tests ────────────────────────────────────────────────────

class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_readiness_check(self, client):
        response = await client.get("/ready")
        assert response.status_code == 200
        assert response.json()["check_mode"] == "lightweight-local"

    @pytest.mark.asyncio
    async def test_root(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        assert response.json()["service"] == "auth-service"


class TestAuthRegistration:
    @pytest.mark.asyncio
    async def test_register_success(self, client):
        response = await client.post("/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "Password123!",
            "full_name": "Test User",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client):
        # Register first user
        await client.post("/auth/register", json={
            "email": "dup@example.com",
            "username": "user1",
            "password": "Password123!",
        })
        # Try duplicate
        response = await client.post("/auth/register", json={
            "email": "dup@example.com",
            "username": "user2",
            "password": "Password123!",
        })
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_register_short_password(self, client):
        response = await client.post("/auth/register", json={
            "email": "test2@example.com",
            "username": "user2",
            "password": "short",
        })
        assert response.status_code == 422  # Pydantic validation


class TestAuthLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client):
        # Register
        await client.post("/auth/register", json={
            "email": "login@example.com",
            "username": "loginuser",
            "password": "Password123!",
        })
        # Login
        response = await client.post("/auth/login", json={
            "email": "login@example.com",
            "password": "Password123!",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        await client.post("/auth/register", json={
            "email": "wrong@example.com",
            "username": "wronguser",
            "password": "Password123!",
        })
        response = await client.post("/auth/login", json={
            "email": "wrong@example.com",
            "password": "WrongPassword!",
        })
        assert response.status_code == 401


class TestAuthMe:
    @pytest.mark.asyncio
    async def test_get_me_authenticated(self, client):
        # Register and login
        await client.post("/auth/register", json={
            "email": "me@example.com",
            "username": "meuser",
            "password": "Password123!",
        })
        login_resp = await client.post("/auth/login", json={
            "email": "me@example.com",
            "password": "Password123!",
        })
        token = login_resp.json()["access_token"]

        # Call /auth/me
        response = await client.get("/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert response.status_code == 200
        assert response.json()["email"] == "me@example.com"

    @pytest.mark.asyncio
    async def test_get_me_unauthenticated(self, client):
        response = await client.get("/auth/me")
        assert response.status_code == 403  # No token
