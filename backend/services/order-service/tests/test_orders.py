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
        resp = await client.get("/orders", headers={"X-User-ID": "550e8400-e29b-41d4-a716-446655440000"})
        assert resp.status_code == 200
        assert resp.json() == []
