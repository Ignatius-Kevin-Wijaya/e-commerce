"""
Route table — maps incoming paths to backend microservices.

LEARNING NOTES:
- The gateway acts as a single entry point for all client requests.
- Each route entry specifies which backend service handles it and whether
  authentication is required.
- Protected routes require a valid JWT; the gateway validates the token
  and adds X-User-ID header before forwarding.
"""

import os
from dataclasses import dataclass
from typing import Optional

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8001")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8002")
CART_SERVICE_URL = os.getenv("CART_SERVICE_URL", "http://localhost:8003")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:8004")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8005")
SHIPPING_RATE_SERVICE_URL = os.getenv("SHIPPING_RATE_SERVICE_URL", "http://localhost:8006")


@dataclass
class RouteConfig:
    path_prefix: str
    upstream_url: str
    requires_auth: bool = False
    strip_prefix: bool = False


ROUTES: list[RouteConfig] = [
    # Auth endpoints (no auth required for login/register)
    RouteConfig("/auth", AUTH_SERVICE_URL, requires_auth=False),

    # Product endpoints (public read, auth for write)
    RouteConfig("/products", PRODUCT_SERVICE_URL, requires_auth=False),
    RouteConfig("/categories", PRODUCT_SERVICE_URL, requires_auth=False),

    # Cart endpoints (auth required)
    RouteConfig("/cart", CART_SERVICE_URL, requires_auth=True),

    # Order endpoints (auth required)
    RouteConfig("/orders", ORDER_SERVICE_URL, requires_auth=True),

    # Payment endpoints (auth required)
    RouteConfig("/payments", PAYMENT_SERVICE_URL, requires_auth=True),
    RouteConfig("/webhooks", PAYMENT_SERVICE_URL, requires_auth=False),

    # Shipping quote endpoints (public quote estimation)
    RouteConfig("/shipping", SHIPPING_RATE_SERVICE_URL, requires_auth=False),
]


def find_route(path: str) -> Optional[RouteConfig]:
    """Find the route config that matches the given path."""
    for route in ROUTES:
        if path.startswith(route.path_prefix):
            return route
    return None
