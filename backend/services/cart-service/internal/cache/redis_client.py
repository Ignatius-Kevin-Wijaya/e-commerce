"""
Redis client wrapper for the cart service.

LEARNING NOTES:
- Redis is an in-memory key-value store — extremely fast (sub-millisecond reads).
- We use it here because carts are temporary and don't need ACID guarantees.
- HSET/HGET stores cart items as a hash: key=cart:{user_id}, field=product_id, value=JSON.
- TTL (Time-To-Live) automatically expires idle carts after 7 days.
"""

import os
from typing import Optional

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CART_TTL = int(os.getenv("CART_TTL_SECONDS", "604800"))  # 7 days

_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create the Redis connection pool (singleton)."""
    global _pool
    if _pool is None:
        _pool = redis.from_url(REDIS_URL, decode_responses=True)
    return _pool


async def close_redis():
    """Close the Redis connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def cart_key(user_id: str) -> str:
    """Build the Redis key for a user's cart."""
    return f"cart:{user_id}"
