"""Payment HTTP handler."""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from internal.repository.payment_repository import PaymentRepository
from internal.service.payment_service import PaymentService, PaymentServiceError

router = APIRouter(prefix="/payments", tags=["Payments"])


class CreatePaymentRequest(BaseModel):
    order_id: str
    amount: float
    currency: str = "USD"
    idempotency_key: Optional[str] = None


class PaymentResponse(BaseModel):
    id: str
    order_id: str
    user_id: str
    amount: float
    currency: str
    status: str
    provider: str
    provider_payment_id: Optional[str]
    idempotency_key: str
    error_message: Optional[str]
    created_at: str
    updated_at: str


async def get_payment_service(request: Request) -> PaymentService:
    db: AsyncSession = request.state.db
    repo = PaymentRepository(db)
    return PaymentService(repo)


def payment_to_response(p) -> PaymentResponse:
    return PaymentResponse(
        id=str(p.id),
        order_id=str(p.order_id),
        user_id=str(p.user_id),
        amount=float(p.amount),
        currency=p.currency,
        status=p.status.value,
        provider=p.provider,
        provider_payment_id=p.provider_payment_id,
        idempotency_key=p.idempotency_key,
        error_message=p.error_message,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


@router.post("", response_model=PaymentResponse, status_code=201)
async def create_payment(
    body: CreatePaymentRequest,
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: PaymentService = Depends(get_payment_service),
):
    """Create a payment for an order."""
    try:
        payment = await service.create_payment(
            order_id=UUID(body.order_id),
            user_id=UUID(x_user_id),
            amount=Decimal(str(body.amount)),
            currency=body.currency,
            idempotency_key=body.idempotency_key,
        )
        return payment_to_response(payment)
    except PaymentServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: UUID,
    service: PaymentService = Depends(get_payment_service),
):
    try:
        payment = await service.get_payment(payment_id)
        return payment_to_response(payment)
    except PaymentServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/order/{order_id}", response_model=PaymentResponse)
async def get_payment_by_order(
    order_id: UUID,
    service: PaymentService = Depends(get_payment_service),
):
    try:
        payment = await service.get_payment_by_order(order_id)
        return payment_to_response(payment)
    except PaymentServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
