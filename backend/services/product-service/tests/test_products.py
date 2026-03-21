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
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestProductHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_root(self, client):
        resp = await client.get("/")
        assert resp.json()["service"] == "product-service"


class TestProducts:
    @pytest.mark.asyncio
    async def test_create_and_get_product(self, client):
        resp = await client.post("/products", json={
            "name": "Test Widget",
            "description": "A test product",
            "price": 29.99,
            "stock": 100,
        })
        assert resp.status_code == 201
        product = resp.json()
        assert product["name"] == "Test Widget"

        # Get by ID
        pid = product["id"]
        resp2 = await client.get(f"/products/{pid}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Test Widget"

    @pytest.mark.asyncio
    async def test_list_products(self, client):
        await client.post("/products", json={"name": "A", "price": 10, "stock": 5})
        await client.post("/products", json={"name": "B", "price": 20, "stock": 10})

        resp = await client.get("/products")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_delete_product(self, client):
        resp = await client.post("/products", json={"name": "Deleteme", "price": 5, "stock": 1})
        pid = resp.json()["id"]

        del_resp = await client.delete(f"/products/{pid}")
        assert del_resp.status_code == 204

        get_resp = await client.get(f"/products/{pid}")
        assert get_resp.status_code == 404
