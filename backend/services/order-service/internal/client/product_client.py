"""
HTTP client for the Product Service.

LEARNING NOTES:
- This is inter-service communication: Order Service calling Product Service over HTTP.
- We use httpx (async HTTP client) with timeouts and basic error handling.
- In production, you'd add circuit breaker, retries, and service discovery.

SECURITY NOTE on X-Is-Admin header:
- The stock decrease/increase endpoints now require admin authorization.
- Internal service-to-service calls are trusted (they originate from the same
  Kubernetes cluster, not from the public internet).
- We send X-Is-Admin: true here to tell the product service this is a legitimate
  internal call (e.g. "order was placed, reduce stock").
- This is safe because ProductClient is only used by the order-service (a server-side
  process), never by client-controlled code. The header cannot be forged by a browser.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8002")
TIMEOUT = 10.0  # seconds

# Internal service-to-service calls are trusted as admin-level operations.
# These headers are sent only by server-side code, never by the client.
_INTERNAL_HEADERS = {"X-Is-Admin": "true"}


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
        except httpx.RequestError as e:
            logger.warning("ProductClient.get_product failed for %s: %s", product_id, e)
            return None

    async def check_stock(self, product_id: str, quantity: int) -> bool:
        """Check if sufficient stock exists for a product."""
        product = await self.get_product(product_id)
        if not product:
            return False
        return product.get("stock", 0) >= quantity

    async def decrease_stock(self, product_id: str, quantity: int) -> bool:
        """Decrease stock in the Product Service after an order is created."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.patch(
                    f"{self.base_url}/products/{product_id}/stock/decrease",
                    json={"quantity": quantity},
                    headers=_INTERNAL_HEADERS,  # trusted internal call
                )
                if resp.status_code != 200:
                    logger.warning(
                        "decrease_stock returned %s for product %s: %s",
                        resp.status_code, product_id, resp.text,
                    )
                    return False
                return True
        except httpx.RequestError as e:
            logger.warning("decrease_stock request failed for %s: %s", product_id, e)
            return False

    async def increase_stock(self, product_id: str, quantity: int) -> bool:
        """Increase stock in the Product Service after an order is cancelled."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.patch(
                    f"{self.base_url}/products/{product_id}/stock/increase",
                    json={"quantity": quantity},
                    headers=_INTERNAL_HEADERS,  # trusted internal call
                )
                if resp.status_code != 200:
                    logger.warning(
                        "increase_stock returned %s for product %s: %s",
                        resp.status_code, product_id, resp.text,
                    )
                    return False
                return True
        except httpx.RequestError as e:
            logger.warning("increase_stock request failed for %s: %s", product_id, e)
            return False

