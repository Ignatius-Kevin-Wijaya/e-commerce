"""Order HTTP handlers."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from internal.model.order import OrderStatus
from internal.repository.order_repository import OrderRepository
from internal.service.order_service import OrderService, OrderServiceError

router = APIRouter(prefix="/orders", tags=["Orders"])


# ── Schemas ──────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    shipping_address: Optional[str] = None
    notes: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    status: str


class OrderItemResponse(BaseModel):
    id: str
    product_id: str
    product_name: str
    price: float
    quantity: int
    subtotal: float


class OrderResponse(BaseModel):
    id: str
    user_id: str
    status: str
    total_amount: float
    shipping_address: Optional[str]
    notes: Optional[str]
    items: List[OrderItemResponse]
    created_at: str
    updated_at: str


# ── Dependencies ─────────────────────────────────────────────

async def get_order_service(request: Request) -> OrderService:
    db: AsyncSession = request.state.db
    repo = OrderRepository(db)
    return OrderService(repo)


def order_to_response(order) -> OrderResponse:
    return OrderResponse(
        id=str(order.id),
        user_id=str(order.user_id),
        status=order.status.value,
        total_amount=float(order.total_amount),
        shipping_address=order.shipping_address,
        notes=order.notes,
        items=[
            OrderItemResponse(
                id=str(item.id),
                product_id=str(item.product_id),
                product_name=item.product_name,
                price=float(item.price),
                quantity=item.quantity,
                subtotal=float(item.price * item.quantity),
            )
            for item in order.items
        ],
        created_at=order.created_at.isoformat(),
        updated_at=order.updated_at.isoformat(),
    )


# ── Endpoints ──────────────────────────────────────────────

@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    body: CreateOrderRequest,
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: OrderService = Depends(get_order_service),
):
    """Create an order from the user's current cart."""
    try:
        order = await service.create_order_from_cart(
            user_id=x_user_id,
            shipping_address=body.shipping_address,
            notes=body.notes,
        )
        return order_to_response(order)
    except OrderServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("", response_model=List[OrderResponse])
async def list_orders(
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: OrderService = Depends(get_order_service),
):
    """Get the current user's orders."""
    orders = await service.get_user_orders(UUID(x_user_id))
    return [order_to_response(o) for o in orders]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: OrderService = Depends(get_order_service),
):
    """Get a specific order by ID."""
    try:
        order = await service.get_order(order_id, UUID(x_user_id))
        return order_to_response(order)
    except OrderServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: UUID,
    body: UpdateStatusRequest,
    service: OrderService = Depends(get_order_service),
):
    """Update the status of an order (admin / internal)."""
    try:
        new_status = OrderStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    try:
        order = await service.update_order_status(order_id, new_status)
        return order_to_response(order)
    except OrderServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
