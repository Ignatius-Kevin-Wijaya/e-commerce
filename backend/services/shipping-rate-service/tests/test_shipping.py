"""Shipping rate service tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


class FakeShippingService:
    async def get_quotes(self, request):
        total_weight_grams = sum(item["weight_grams"] * item["quantity"] for item in request["items"])
        return {
            "request_id": "test-request",
            "destination_zone": request["destination_zone"],
            "priority": request["priority"],
            "total_weight_grams": total_weight_grams,
            "quote_count": 3,
            "quotes": [
                {
                    "carrier": "fastship",
                    "service_level": "express",
                    "amount": 14.5,
                    "currency": "USD",
                    "estimated_days": 1,
                    "observed_delay_ms": 210,
                },
                {
                    "carrier": "ecopost",
                    "service_level": "standard",
                    "amount": 9.25,
                    "currency": "USD",
                    "estimated_days": 3,
                    "observed_delay_ms": 420,
                },
                {
                    "carrier": "globex",
                    "service_level": "economy",
                    "amount": 12.0,
                    "currency": "USD",
                    "estimated_days": 4,
                    "observed_delay_ms": 630,
                },
            ],
            "recommended": {
                "cheapest_carrier": "ecopost",
                "fastest_carrier": "fastship",
            },
        }


@pytest_asyncio.fixture
async def client():
    from app.main import app
    from internal.handler.shipping_handler import get_shipping_service

    app.dependency_overrides[get_shipping_service] = lambda: FakeShippingService()
    transport = ASGITransport(app=app)
    headers = {"X-Internal-Gateway-Secret": "dev_secret_gateway_key"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac
    app.dependency_overrides.clear()


class TestShippingHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "shipping-rate-service"

    @pytest.mark.asyncio
    async def test_root(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.json()["service"] == "shipping-rate-service"


class TestShippingQuotes:
    @pytest.mark.asyncio
    async def test_quotes_endpoint(self, client):
        resp = await client.post(
            "/shipping/quotes",
            json={
                "destination_zone": "regional",
                "priority": "express",
                "items": [
                    {"sku": "sku-1", "quantity": 2, "weight_grams": 350},
                    {"sku": "sku-2", "quantity": 1, "weight_grams": 500},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_weight_grams"] == 1200
        assert data["quote_count"] == 3
        assert data["recommended"]["cheapest_carrier"] == "ecopost"

    @pytest.mark.asyncio
    async def test_gateway_secret_required(self, client):
        resp = await client.post(
            "/shipping/quotes",
            json={
                "destination_zone": "domestic",
                "priority": "standard",
                "items": [{"sku": "sku-1", "quantity": 1, "weight_grams": 100}],
            },
            headers={"X-Internal-Gateway-Secret": "wrong"},
        )
        assert resp.status_code == 403
