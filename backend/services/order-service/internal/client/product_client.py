"""
HTTP client for the Product Service.

LEARNING NOTES:
- This is inter-service communication: Order Service calling Product Service over HTTP.
- We use httpx (async HTTP client) with timeouts and basic error handling.
- In production, you'd add circuit breaker, retries, and service discovery.
"""

import os
from typing import Optional
from uuid import UUID

import httpx

PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8002")
TIMEOUT = 10.0  # seconds


class ProductClient:
    def __init__(self):
        self.base_url = PRODUCT_SERVICE_URL

    async def get_product(self, product_id: str) -> Optional[dict]:
        """Fetch a product by ID from the Product Service."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/products/{product_id}")
                if resp.status_code == 200:
                    return resp.json()
                return None
        except httpx.RequestError:
            return None

    async def check_stock(self, product_id: str, quantity: int) -> bool:
        """Check if sufficient stock exists for a product."""
        product = await self.get_product(product_id)
        if not product:
            return False
        return product.get("stock", 0) >= quantity
