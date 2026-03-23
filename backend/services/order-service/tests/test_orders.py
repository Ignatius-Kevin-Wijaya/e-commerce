"""Order Service tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.model.order import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_order.db"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    from app.main import app
    from internal.handler.order_handler import get_order_service
    from internal.repository.order_repository import OrderRepository
    from internal.service.order_service import OrderService

    async def override_get_order_service():
        async with TestSession() as session:
            repo = OrderRepository(session)
            yield OrderService(repo)

    app.dependency_overrides[get_order_service] = override_get_order_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

ADMIN_HEADERS = {"X-Is-Admin": "true", "X-User-ID": "550e8400-e29b-41d4-a716-446655441111"}
USER_HEADERS = {"X-Is-Admin": "false", "X-User-ID": "550e8400-e29b-41d4-a716-446655440000"}


class TestOrderHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_root(self, client):
        resp = await client.get("/")
        assert resp.json()["service"] == "order-service"


class TestOrders:
    @pytest.mark.asyncio
    async def test_list_orders_empty(self, client):
        resp = await client.get("/orders", headers=USER_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []


class TestOrderStatusAuthorization:
    @pytest.mark.asyncio
    async def test_update_status_without_admin_returns_403(self, client):
        """A regular user cannot update order status."""
        resp = await client.patch(
            "/orders/550e8400-e29b-41d4-a716-446655449999/status",
            json={"status": "shipped"},
            headers=USER_HEADERS,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_status_with_admin_returns_404_not_403(self, client):
        """An admin user bypasses the 403 auth block (fails with 404 since order doesn't exist)."""
        resp = await client.patch(
            "/orders/550e8400-e29b-41d4-a716-446655449999/status",
            json={"status": "shipped"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, "Admin should bypass auth and hit the 404 Not Found block"
