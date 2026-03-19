"""Cart Service tests (mocking Redis)."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked Redis."""
    # Mock Redis before importing the app
    mock_redis = AsyncMock()
    mock_redis.hgetall.return_value = {}
    mock_redis.hset.return_value = True
    mock_redis.hdel.return_value = 1
    mock_redis.hlen.return_value = 0
    mock_redis.expire.return_value = True
    mock_redis.delete.return_value = True
    mock_redis.ping.return_value = True

    with patch("internal.cache.redis_client.get_redis", return_value=mock_redis):
        from cmd.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestCartHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestCartEndpoints:
    @pytest.mark.asyncio
    async def test_get_empty_cart(self, client):
        resp = await client.get("/cart", headers={"X-User-ID": "user-123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-123"
        assert data["items"] == []
        assert data["total"] == 0.0

    @pytest.mark.asyncio
    async def test_add_item(self, client):
        resp = await client.post("/cart/items", json={
            "product_id": "prod-1",
            "product_name": "Widget",
            "price": 29.99,
            "quantity": 2,
        }, headers={"X-User-ID": "user-123"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_clear_cart(self, client):
        resp = await client.delete("/cart", headers={"X-User-ID": "user-123"})
        assert resp.status_code == 204
