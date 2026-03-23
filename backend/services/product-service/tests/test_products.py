"""Product Service tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.model.category import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_product.db"
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
    from internal.handler.product_handler import get_product_service
    from internal.repository.product_repository import ProductRepository
    from internal.service.product_service import ProductService

    async def override_get_product_service():
        async with TestSession() as session:
            repo = ProductRepository(session)
            yield ProductService(repo)

    app.dependency_overrides[get_product_service] = override_get_product_service
    transport = ASGITransport(app=app)
    headers = {"X-Internal-Gateway-Secret": "dev_secret_gateway_key"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

ADMIN_HEADERS = {"X-Is-Admin": "true"}
USER_HEADERS = {"X-Is-Admin": "false"}

SAMPLE_PRODUCT = {
    "name": "Test Widget",
    "description": "A test product",
    "price": 29.99,
    "stock": 100,
}


# ── Health tests ──────────────────────────────────────────────────────────────

class TestProductHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_root(self, client):
        resp = await client.get("/")
        assert resp.json()["service"] == "product-service"


# ── Admin Authorization tests ─────────────────────────────────────────────────
#
# LEARNING NOTE:
# We test the require_admin dependency directly via the HTTP layer.
# FastAPI's dependency injection runs even in test mode, so if we don't send
# X-Is-Admin: true the dependency raises 403 before the handler body runs.
# This proves the security control works independently of who calls the service.

class TestAdminAuthorization:
    @pytest.mark.asyncio
    async def test_create_product_without_admin_returns_403(self, client):
        """A regular user (X-Is-Admin: false) cannot create products."""
        resp = await client.post("/products", json=SAMPLE_PRODUCT, headers=USER_HEADERS)
        assert resp.status_code == 403, "Regular user should be blocked from creating products"

    @pytest.mark.asyncio
    async def test_create_product_no_header_returns_403(self, client):
        """Missing X-Is-Admin header (treats as false — safe default) should be blocked."""
        resp = await client.post("/products", json=SAMPLE_PRODUCT)
        assert resp.status_code == 403, "Missing admin header should be blocked"

    @pytest.mark.asyncio
    async def test_create_product_with_admin_returns_201(self, client):
        """An admin user (X-Is-Admin: true) can create products."""
        resp = await client.post("/products", json=SAMPLE_PRODUCT, headers=ADMIN_HEADERS)
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Widget"

    @pytest.mark.asyncio
    async def test_update_product_without_admin_returns_403(self, client):
        """A regular user cannot update products."""
        # First create a product as admin
        create_resp = await client.post("/products", json=SAMPLE_PRODUCT, headers=ADMIN_HEADERS)
        pid = create_resp.json()["id"]

        # Attempt to update as regular user — must be blocked
        resp = await client.put(f"/products/{pid}", json={"name": "Hacked"}, headers=USER_HEADERS)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_product_without_admin_returns_403(self, client):
        """A regular user cannot delete products."""
        create_resp = await client.post("/products", json=SAMPLE_PRODUCT, headers=ADMIN_HEADERS)
        pid = create_resp.json()["id"]

        resp = await client.delete(f"/products/{pid}", headers=USER_HEADERS)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_decrease_stock_without_admin_returns_403(self, client):
        """A regular user cannot manipulate stock (decrease)."""
        create_resp = await client.post("/products", json=SAMPLE_PRODUCT, headers=ADMIN_HEADERS)
        pid = create_resp.json()["id"]

        resp = await client.patch(
            f"/products/{pid}/stock/decrease",
            json={"quantity": 5},
            headers=USER_HEADERS,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_increase_stock_without_admin_returns_403(self, client):
        """A regular user cannot manipulate stock (increase)."""
        create_resp = await client.post("/products", json=SAMPLE_PRODUCT, headers=ADMIN_HEADERS)
        pid = create_resp.json()["id"]

        resp = await client.patch(
            f"/products/{pid}/stock/increase",
            json={"quantity": 5},
            headers=USER_HEADERS,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_category_without_admin_returns_403(self, client):
        """A regular user cannot create categories."""
        resp = await client.post(
            "/categories",
            json={"name": "Fake Category"},
            headers=USER_HEADERS,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_category_with_admin_returns_201(self, client):
        """An admin user can create categories."""
        resp = await client.post(
            "/categories",
            json={"name": "Electronics"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Electronics"


# ── Public read-access tests ──────────────────────────────────────────────────
#
# LEARNING NOTE:
# GET endpoints deliberately do NOT require admin. Anyone can browse the product
# catalog. This is a common e-commerce pattern: read is public, write is protected.

class TestProducts:
    @pytest.mark.asyncio
    async def test_create_and_get_product(self, client):
        resp = await client.post("/products", json=SAMPLE_PRODUCT, headers=ADMIN_HEADERS)
        assert resp.status_code == 201
        product = resp.json()
        assert product["name"] == "Test Widget"

        # GET is public — no admin header needed
        pid = product["id"]
        resp2 = await client.get(f"/products/{pid}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Test Widget"

    @pytest.mark.asyncio
    async def test_list_products(self, client):
        await client.post("/products", json={"name": "A", "price": 10, "stock": 5}, headers=ADMIN_HEADERS)
        await client.post("/products", json={"name": "B", "price": 20, "stock": 10}, headers=ADMIN_HEADERS)

        resp = await client.get("/products")  # No auth needed for list
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_delete_product(self, client):
        resp = await client.post("/products", json={"name": "Deleteme", "price": 5, "stock": 1}, headers=ADMIN_HEADERS)
        pid = resp.json()["id"]

        del_resp = await client.delete(f"/products/{pid}", headers=ADMIN_HEADERS)
        assert del_resp.status_code == 204

        get_resp = await client.get(f"/products/{pid}")
        assert get_resp.status_code == 404
