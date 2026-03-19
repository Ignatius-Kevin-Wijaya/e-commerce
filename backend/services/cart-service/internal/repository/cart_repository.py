"""
Cart repository — Redis-backed storage for shopping carts.
"""

import json
from typing import Dict, Optional

from internal.cache.redis_client import CART_TTL, cart_key, get_redis
from internal.model.cart_item import CartItem


class CartRepository:
    async def get_cart_items(self, user_id: str) -> Dict[str, CartItem]:
        """Get all items in a user's cart."""
        r = await get_redis()
        raw = await r.hgetall(cart_key(user_id))
        items = {}
        for product_id, item_json in raw.items():
            items[product_id] = CartItem(**json.loads(item_json))
        return items

    async def add_item(self, user_id: str, item: CartItem) -> None:
        """Add or update an item in the cart."""
        r = await get_redis()
        key = cart_key(user_id)
        await r.hset(key, item.product_id, item.model_dump_json())
        await r.expire(key, CART_TTL)  # Reset TTL on every update

    async def remove_item(self, user_id: str, product_id: str) -> bool:
        """Remove an item from the cart. Returns True if item existed."""
        r = await get_redis()
        removed = await r.hdel(cart_key(user_id), product_id)
        return removed > 0

    async def update_quantity(self, user_id: str, product_id: str, quantity: int) -> Optional[CartItem]:
        """Update quantity of an existing item."""
        r = await get_redis()
        key = cart_key(user_id)
        raw = await r.hget(key, product_id)
        if not raw:
            return None

        item = CartItem(**json.loads(raw))
        item.quantity = quantity
        await r.hset(key, product_id, item.model_dump_json())
        await r.expire(key, CART_TTL)
        return item

    async def clear_cart(self, user_id: str) -> None:
        """Remove all items from the cart."""
        r = await get_redis()
        await r.delete(cart_key(user_id))

    async def get_item_count(self, user_id: str) -> int:
        """Get number of distinct items in the cart."""
        r = await get_redis()
        return await r.hlen(cart_key(user_id))
