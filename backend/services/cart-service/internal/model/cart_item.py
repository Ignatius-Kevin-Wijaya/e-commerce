"""
Cart item model (Pydantic, not SQLAlchemy — cart is stored in Redis).

LEARNING NOTES:
- Unlike other services, the cart has NO SQL database.
- Cart items are stored in Redis as JSON — fast, ephemeral, TTL-based expiry.
- This Pydantic model is used for request/response validation and Redis serialization.
"""

from pydantic import BaseModel, Field


class CartItem(BaseModel):
    product_id: str
    product_name: str = ""
    price: float = 0.0
    quantity: int = Field(..., ge=1)
    image_url: str = ""


class Cart(BaseModel):
    user_id: str
    items: list[CartItem] = []
    total: float = 0.0

    def recalculate_total(self):
        self.total = sum(item.price * item.quantity for item in self.items)
