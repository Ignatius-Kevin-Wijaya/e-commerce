"""Carrier mock service tests."""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setenv("CARRIER_DELAY_SCALE", "0")
    from app.main import app

    transport = ASGITransport(app=app)
    headers = {"X-Internal-Gateway-Secret": "dev_secret_gateway_key"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac


class TestCarrierHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "carrier-mock-service"


class TestCarrierQuotes:
    @pytest.mark.asyncio
    async def test_quote(self, client):
        resp = await client.post(
            "/mock-carriers/fastship/quote",
            json={
                "request_id": "req-1",
                "destination_zone": "regional",
                "priority": "express",
                "total_weight_grams": 1200,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["carrier"] == "fastship"
        assert data["amount"] > 0
        assert data["estimated_days"] >= 1

    @pytest.mark.asyncio
    async def test_secret_required(self, client):
        resp = await client.post(
            "/mock-carriers/fastship/quote",
            json={
                "request_id": "req-1",
                "destination_zone": "regional",
                "priority": "standard",
                "total_weight_grams": 1200,
            },
            headers={"X-Internal-Gateway-Secret": "bad-secret"},
        )
        assert resp.status_code == 403
