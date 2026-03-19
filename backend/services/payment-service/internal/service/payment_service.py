"""Payment service — business logic with idempotency and Stripe simulation."""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from internal.model.payment import Payment, PaymentStatus
from internal.provider.stripe_client import StripeClient
from internal.repository.payment_repository import PaymentRepository


class PaymentServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PaymentService:
    def __init__(self, repo: PaymentRepository):
        self.repo = repo
        self.stripe = StripeClient()

    async def create_payment(
        self,
        order_id: UUID,
        user_id: UUID,
        amount: Decimal,
        currency: str = "USD",
        idempotency_key: Optional[str] = None,
    ) -> Payment:
        """Process a payment for an order."""
        # Generate idempotency key if not provided
        if not idempotency_key:
            idempotency_key = f"{order_id}:{user_id}"

        # Idempotency check — return existing payment if same key
        existing = await self.repo.find_by_idempotency_key(idempotency_key)
        if existing:
            return existing

        # Create pending payment record
        payment = Payment(
            order_id=order_id,
            user_id=user_id,
            amount=amount,
            currency=currency.upper(),
            status=PaymentStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        payment = await self.repo.create(payment)

        # Update to processing
        await self.repo.update_status(payment.id, PaymentStatus.PROCESSING)

        # Call Stripe (simulated)
        try:
            amount_cents = int(amount * 100)
            intent = await self.stripe.create_payment_intent(
                amount_cents=amount_cents,
                currency=currency.lower(),
                idempotency_key=idempotency_key,
            )

            if intent.status == "succeeded":
                payment = await self.repo.update_status(
                    payment.id,
                    PaymentStatus.SUCCESS,
                    provider_payment_id=intent.id,
                )
            else:
                payment = await self.repo.update_status(
                    payment.id,
                    PaymentStatus.FAILED,
                    provider_payment_id=intent.id,
                    error_message=f"Stripe status: {intent.status}",
                )

        except Exception as e:
            payment = await self.repo.update_status(
                payment.id,
                PaymentStatus.FAILED,
                error_message=str(e),
            )

        return payment

    async def get_payment(self, payment_id: UUID) -> Payment:
        payment = await self.repo.find_by_id(payment_id)
        if not payment:
            raise PaymentServiceError("Payment not found", 404)
        return payment

    async def get_payment_by_order(self, order_id: UUID) -> Payment:
        payment = await self.repo.find_by_order_id(order_id)
        if not payment:
            raise PaymentServiceError("Payment not found for this order", 404)
        return payment

    async def process_webhook(self, event_type: str, data: dict) -> None:
        """Handle incoming Stripe webhook events."""
        if event_type == "payment_intent.succeeded":
            provider_id = data.get("id")
            # In production, look up payment by provider_id and update status
            pass
        elif event_type == "payment_intent.payment_failed":
            pass
