"""
HTTP client for the Cart Service.
Fetches the user's cart to create an order from it.
"""

import os
from typing import Optional

import httpx

CART_SERVICE_URL = os.getenv("CART_SERVICE_URL", "http://localhost:8003")
TIMEOUT = 10.0


class CartClient:
    def __init__(self):
        self.base_url = CART_SERVICE_URL

    async def get_cart(self, user_id: str) -> Optional[dict]:
        """Fetch the user's cart from the Cart Service."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(
                    f"{self.base_url}/cart",
                    headers={"X-User-ID": user_id},
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
        except httpx.RequestError:
            return None

    async def clear_cart(self, user_id: str) -> bool:
        """Clear the user's cart after order creation."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.delete(
                    f"{self.base_url}/cart",
                    headers={"X-User-ID": user_id},
                )
                return resp.status_code == 204
        except httpx.RequestError:
            return False
