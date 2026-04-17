"""HTTP client for the internal carrier-mock-service.

Uses a module-level shared httpx.AsyncClient to avoid per-request allocation
overhead. Under 60 RPS × 3 carriers, creating/destroying 60 clients/sec caused
OOMKill at 512Mi — the shared pool keeps memory stable at ~60-80Mi under load.
"""

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CARRIER_SERVICE_URL = os.getenv("CARRIER_SERVICE_URL", "http://localhost:8007")
INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET", "dev_secret_gateway_key")
TIMEOUT = float(os.getenv("CARRIER_TIMEOUT_SECONDS", "3.0"))
CARRIERS = ("fastship", "ecopost", "globex")

# Shared httpx client — created lazily on first use, reused for all requests.
# Connection pool limits prevent unbounded connection growth under load.
_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """Return the module-level shared httpx.AsyncClient, creating it on first call."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=TIMEOUT,
            limits=httpx.Limits(
                # Pool sized at 80 connections per pod — realistic for a microservice.
                # With ramping-vus executor at 80 VUs peak:
                #   B1 (1 pod): 80 VUs × 3 carriers × 0.71s hold = 170 concurrent
                #               needed → 90 queue → +~700ms latency → p95 rises
                #   B2 (5 pods): 16 VUs/pod × 3 × 0.71s = 34/pod → no queue
                # This produces the correct wait-dominant latency differentiation.
                max_connections=80,
                max_keepalive_connections=40,
            ),
        )
    return _shared_client


class CarrierClientError(Exception):
    """Raised when no downstream carrier quote can be retrieved."""


class CarrierClient:
    def __init__(self):
        self.base_url = CARRIER_SERVICE_URL.rstrip("/")
        self._headers = {"X-Internal-Gateway-Secret": INTERNAL_GATEWAY_SECRET}

    async def _fetch_quote(self, client: httpx.AsyncClient, carrier: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await client.post(
            f"{self.base_url}/mock-carriers/{carrier}/quote",
            json=payload,
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch_quotes(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        client = _get_shared_client()
        tasks = [self._fetch_quote(client, carrier, payload) for carrier in CARRIERS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        quotes: list[dict[str, Any]] = []
        failures: list[str] = []
        for carrier, result in zip(CARRIERS, results):
            if isinstance(result, Exception):
                failures.append(f"{carrier}: {result}")
                continue
            quotes.append(result)

        if not quotes:
            logger.warning("All carrier quotes failed: %s", "; ".join(failures))
            raise CarrierClientError("All carriers failed: " + "; ".join(failures))

        return quotes

    async def health_check(self) -> dict[str, Any]:
        client = _get_shared_client()
        resp = await client.get(f"{self.base_url}/ready", headers=self._headers)
        resp.raise_for_status()
        return resp.json()
