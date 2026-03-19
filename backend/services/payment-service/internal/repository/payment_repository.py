"""Payment repository — DB access for payments."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from internal.model.payment import Payment, PaymentStatus


class PaymentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, payment: Payment) -> Payment:
        self.db.add(payment)
        await self.db.commit()
        await self.db.refresh(payment)
        return payment

    async def find_by_id(self, payment_id: UUID) -> Optional[Payment]:
        result = await self.db.execute(select(Payment).where(Payment.id == payment_id))
        return result.scalar_one_or_none()

    async def find_by_order_id(self, order_id: UUID) -> Optional[Payment]:
        result = await self.db.execute(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.desc())
        )
        return result.scalar_one_or_none()

    async def find_by_idempotency_key(self, key: str) -> Optional[Payment]:
        result = await self.db.execute(
            select(Payment).where(Payment.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        payment_id: UUID,
        status: PaymentStatus,
        provider_payment_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Payment]:
        from datetime import datetime
        values = {"status": status, "updated_at": datetime.utcnow()}
        if provider_payment_id:
            values["provider_payment_id"] = provider_payment_id
        if error_message:
            values["error_message"] = error_message

        await self.db.execute(update(Payment).where(Payment.id == payment_id).values(**values))
        await self.db.commit()
        return await self.find_by_id(payment_id)
