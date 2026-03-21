"""Payment Service tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.model.payment import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_payment.db"
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
    from internal.handler.payment_handler import get_payment_service
    from internal.repository.payment_repository import PaymentRepository
    from internal.service.payment_service import PaymentService

    async def override_get_payment_service():
        async with TestSession() as session:
            repo = PaymentRepository(session)
            yield PaymentService(repo)

    app.dependency_overrides[get_payment_service] = override_get_payment_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestPaymentHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_root(self, client):
        resp = await client.get("/")
        assert resp.json()["service"] == "payment-service"


class TestPayments:
    @pytest.mark.asyncio
    async def test_create_payment(self, client):
        resp = await client.post("/payments", json={
            "order_id": "550e8400-e29b-41d4-a716-446655440000",
            "amount": 99.99,
            "currency": "USD",
            "idempotency_key": "test-key-1",
        }, headers={"X-User-ID": "550e8400-e29b-41d4-a716-446655440001"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "success"
        assert data["amount"] == 99.99

    @pytest.mark.asyncio
    async def test_idempotent_payment(self, client):
        payload = {
            "order_id": "550e8400-e29b-41d4-a716-446655440002",
            "amount": 50.00,
            "idempotency_key": "idem-key-2",
        }
        headers = {"X-User-ID": "550e8400-e29b-41d4-a716-446655440003"}

        resp1 = await client.post("/payments", json=payload, headers=headers)
        resp2 = await client.post("/payments", json=payload, headers=headers)

        assert resp1.json()["id"] == resp2.json()["id"]  # Same payment returned
