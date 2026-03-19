"""Typed HTTP clients for backend services (used by gateway)."""

import httpx
from typing import Optional

TIMEOUT = 15.0


class ServiceClient:
    """Generic HTTP client for proxying requests to backend services."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def proxy_request(
        self,
        method: str,
        path: str,
        headers: dict,
        body: Optional[bytes] = None,
        query_string: str = "",
    ) -> httpx.Response:
        """Forward an HTTP request to the backend service."""
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"

        # Remove hop-by-hop headers
        forward_headers = {
            k: v for k, v in headers.items()
            if k.lower() not in ("host", "connection", "transfer-encoding")
        }

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=forward_headers,
                content=body,
            )
            return response
