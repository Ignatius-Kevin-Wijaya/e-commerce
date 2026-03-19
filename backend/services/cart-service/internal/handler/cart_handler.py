"""Cart HTTP handlers."""

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from typing import List, Optional

from internal.model.cart_item import CartItem
from internal.repository.cart_repository import CartRepository
from internal.service.cart_service import CartService, CartServiceError

router = APIRouter(prefix="/cart", tags=["Cart"])


# ── Schemas ──────────────────────────────────────────────────

class AddToCartRequest(BaseModel):
    product_id: str
    product_name: str = ""
    price: float = 0.0
    quantity: int = Field(1, ge=1)
    image_url: str = ""


class UpdateQuantityRequest(BaseModel):
    quantity: int = Field(..., ge=1)


class CartItemResponse(BaseModel):
    product_id: str
    product_name: str
    price: float
    quantity: int
    image_url: str
    subtotal: float = 0.0


class CartResponse(BaseModel):
    user_id: str
    items: List[CartItemResponse]
    total: float
    item_count: int


# ── Dependencies ─────────────────────────────────────────────

def get_cart_service() -> CartService:
    return CartService(CartRepository())


def cart_to_response(cart) -> CartResponse:
    return CartResponse(
        user_id=cart.user_id,
        items=[
            CartItemResponse(
                product_id=item.product_id,
                product_name=item.product_name,
                price=item.price,
                quantity=item.quantity,
                image_url=item.image_url,
                subtotal=item.price * item.quantity,
            )
            for item in cart.items
        ],
        total=cart.total,
        item_count=len(cart.items),
    )


# ── Endpoints ──────────────────────────────────────────────
# Note: user_id comes from X-User-ID header (set by API Gateway after auth validation)

@router.get("", response_model=CartResponse)
async def get_cart(
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: CartService = Depends(get_cart_service),
):
    """Get the current user's cart."""
    cart = await service.get_cart(x_user_id)
    return cart_to_response(cart)


@router.post("/items", response_model=CartResponse)
async def add_item(
    body: AddToCartRequest,
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: CartService = Depends(get_cart_service),
):
    """Add an item to the cart."""
    item = CartItem(
        product_id=body.product_id,
        product_name=body.product_name,
        price=body.price,
        quantity=body.quantity,
        image_url=body.image_url,
    )
    try:
        cart = await service.add_to_cart(x_user_id, item)
        return cart_to_response(cart)
    except CartServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put("/items/{product_id}", response_model=CartResponse)
async def update_item_quantity(
    product_id: str,
    body: UpdateQuantityRequest,
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: CartService = Depends(get_cart_service),
):
    """Update quantity of a cart item."""
    try:
        cart = await service.update_item_quantity(x_user_id, product_id, body.quantity)
        return cart_to_response(cart)
    except CartServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/items/{product_id}", response_model=CartResponse)
async def remove_item(
    product_id: str,
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: CartService = Depends(get_cart_service),
):
    """Remove an item from the cart."""
    try:
        cart = await service.remove_from_cart(x_user_id, product_id)
        return cart_to_response(cart)
    except CartServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("", status_code=204)
async def clear_cart(
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: CartService = Depends(get_cart_service),
):
    """Clear all items from the cart."""
    await service.clear_cart(x_user_id)
