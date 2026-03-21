"""Cart service — business logic."""


from internal.model.cart_item import Cart, CartItem
from internal.repository.cart_repository import CartRepository


class CartServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class CartService:
    def __init__(self, repo: CartRepository):
        self.repo = repo

    async def get_cart(self, user_id: str) -> Cart:
        items = await self.repo.get_cart_items(user_id)
        cart = Cart(user_id=user_id, items=list(items.values()))
        cart.recalculate_total()
        return cart

    async def add_to_cart(self, user_id: str, item: CartItem) -> Cart:
        if item.quantity < 1:
            raise CartServiceError("Quantity must be at least 1")

        # Check if item already in cart — if so, increment quantity
        existing_items = await self.repo.get_cart_items(user_id)
        if item.product_id in existing_items:
            existing = existing_items[item.product_id]
            item.quantity += existing.quantity

        await self.repo.add_item(user_id, item)
        return await self.get_cart(user_id)

    async def update_item_quantity(self, user_id: str, product_id: str, quantity: int) -> Cart:
        if quantity < 1:
            raise CartServiceError("Quantity must be at least 1")

        updated = await self.repo.update_quantity(user_id, product_id, quantity)
        if not updated:
            raise CartServiceError("Item not in cart", 404)
        return await self.get_cart(user_id)

    async def remove_from_cart(self, user_id: str, product_id: str) -> Cart:
        removed = await self.repo.remove_item(user_id, product_id)
        if not removed:
            raise CartServiceError("Item not in cart", 404)
        return await self.get_cart(user_id)

    async def clear_cart(self, user_id: str) -> None:
        await self.repo.clear_cart(user_id)
