"""HTTP client for the internal carrier-mock-service."""

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
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            tasks = [self._fetch_quote(client, carrier, payload) for carrier in CARRIERS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        quotes: list[dict[str, Any]] = []
        failures: list[str] = []
        for carrier, result in zip(CARRIERS, results):
            if isinstance(result, Exception):
                failures.append(f"{carrier}: {result}")
                logger.warning("Carrier quote failed for %s: %s", carrier, result)
                continue
            quotes.append(result)

        if not quotes:
            raise CarrierClientError("All carriers failed: " + "; ".join(failures))

        return quotes

    async def health_check(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{self.base_url}/ready", headers=self._headers)
            resp.raise_for_status()
            return resp.json()
