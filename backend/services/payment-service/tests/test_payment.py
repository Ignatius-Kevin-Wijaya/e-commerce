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


# ── Helpers ──────────────────────────────────────────────────────────────────

USER_A_HEADERS = {"X-User-ID": "550e8400-e29b-41d4-a716-44665544000a", "X-Is-Admin": "false"}
USER_B_HEADERS = {"X-User-ID": "550e8400-e29b-41d4-a716-44665544000b", "X-Is-Admin": "false"}
ADMIN_HEADERS = {"X-User-ID": "550e8400-e29b-41d4-a716-446655441111", "X-Is-Admin": "true"}


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
        }, headers=USER_A_HEADERS)
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
        headers = USER_A_HEADERS

        resp1 = await client.post("/payments", json=payload, headers=headers)
        resp2 = await client.post("/payments", json=payload, headers=headers)

        assert resp1.json()["id"] == resp2.json()["id"]


class TestPaymentAuthorization:
    @pytest.mark.asyncio
    async def test_get_payment_idor_protection(self, client):
        """Test that user B cannot see user A's payment, but User A and Admin can."""
        # 1. Create payment as User A
        create_resp = await client.post("/payments", json={
            "order_id": "550e8400-e29b-41d4-a716-44665544000a",
            "amount": 10.00,
            "currency": "USD",
        }, headers=USER_A_HEADERS)
        payment_id = create_resp.json()["id"]

        # 2. Try to get as User B (Should be 403)
        get_b_resp = await client.get(f"/payments/{payment_id}", headers=USER_B_HEADERS)
        assert get_b_resp.status_code == 403
        assert get_b_resp.json()["detail"] == "Not authorized to view this payment"

        # 3. Try to get as User A (Should be 200)
        get_a_resp = await client.get(f"/payments/{payment_id}", headers=USER_A_HEADERS)
        assert get_a_resp.status_code == 200

        # 4. Try to get as Admin (Should be 200)
        get_admin_resp = await client.get(f"/payments/{payment_id}", headers=ADMIN_HEADERS)
        assert get_admin_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_payment_by_order_idor_protection(self, client):
        """Test that user B cannot see user A's payment by order ID."""
        order_id = "550e8400-e29b-41d4-a716-44665544000c"
        # 1. Create payment as User A
        await client.post("/payments", json={
            "order_id": order_id,
            "amount": 20.00,
            "currency": "USD",
        }, headers=USER_A_HEADERS)

        # 2. Try to get by order_id as User B (Should be 403)
        get_b_resp = await client.get(f"/payments/order/{order_id}", headers=USER_B_HEADERS)
        assert get_b_resp.status_code == 403

        # 3. Try to get by order_id as User A (Should be 200)
        get_a_resp = await client.get(f"/payments/order/{order_id}", headers=USER_A_HEADERS)
        assert get_a_resp.status_code == 200
