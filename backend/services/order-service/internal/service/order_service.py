"""
Order service — business logic with inter-service calls.

LEARNING NOTES:
- Creating an order involves calling the Cart Service (to get items) and Product Service
  (to verify stock). This is inter-service communication.
- We DON'T use distributed transactions. Instead, we accept eventual consistency.
- The order status follows a state machine with valid transitions.
"""

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from internal.client.cart_client import CartClient
from internal.client.product_client import ProductClient
from internal.model.order import Order, OrderStatus
from internal.model.order_item import OrderItem
from internal.repository.order_repository import OrderRepository


class OrderServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# Valid status transitions
VALID_TRANSITIONS = {
    OrderStatus.PENDING: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.CONFIRMED: [OrderStatus.SHIPPED, OrderStatus.CANCELLED],
    OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
    OrderStatus.DELIVERED: [],
    OrderStatus.CANCELLED: [],
}


class OrderService:
    def __init__(self, repo: OrderRepository):
        self.repo = repo
        self.product_client = ProductClient()
        self.cart_client = CartClient()

    async def create_order_from_cart(
        self,
        user_id: str,
        shipping_address: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Order:
        """Create an order by pulling items from the cart."""
        # 1. Fetch cart
        cart = await self.cart_client.get_cart(user_id)
        if not cart or not cart.get("items"):
            raise OrderServiceError("Cart is empty", 400)

        # 2. Build order items and verify each product
        order_items = []
        total = Decimal("0")

        for item in cart["items"]:
            product = await self.product_client.get_product(item["product_id"])
            if not product:
                raise OrderServiceError(f"Product {item['product_id']} not found", 404)

            if product.get("stock", 0) < item["quantity"]:
                raise OrderServiceError(
                    f"Insufficient stock for {product['name']} (available: {product['stock']})", 400
                )

            price = Decimal(str(item["price"]))
            order_item = OrderItem(
                product_id=item["product_id"],
                product_name=item.get("product_name", product["name"]),
                price=price,
                quantity=item["quantity"],
            )
            order_items.append(order_item)
            total += price * item["quantity"]

        # 3. Create the order
        order = Order(
            user_id=user_id,
            status=OrderStatus.PENDING,
            total_amount=total,
            shipping_address=shipping_address,
            notes=notes,
            items=order_items,
        )
        created = await self.repo.create(order)

        # 4. Clear the cart (best effort — don't fail the order if this fails)
        await self.cart_client.clear_cart(user_id)

        return created

    async def get_order(self, order_id: UUID, user_id: Optional[UUID] = None) -> Order:
        order = await self.repo.find_by_id(order_id)
        if not order:
            raise OrderServiceError("Order not found", 404)
        if user_id and str(order.user_id) != str(user_id):
            raise OrderServiceError("Not authorized to view this order", 403)
        return order

    async def get_user_orders(self, user_id: UUID) -> List[Order]:
        return await self.repo.find_by_user(user_id)

    async def update_order_status(self, order_id: UUID, new_status: OrderStatus) -> Order:
        order = await self.repo.find_by_id(order_id)
        if not order:
            raise OrderServiceError("Order not found", 404)

        if new_status not in VALID_TRANSITIONS.get(order.status, []):
            raise OrderServiceError(
                f"Cannot transition from {order.status.value} to {new_status.value}", 400
            )

        return await self.repo.update_status(order_id, new_status)
