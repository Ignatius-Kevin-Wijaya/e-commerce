"""Order repository — DB access for orders and order items."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from internal.model.order import Order, OrderStatus


class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, order: Order) -> Order:
        self.db.add(order)
        await self.db.commit()
        return await self.find_by_id(order.id)

    async def find_by_id(self, order_id: UUID) -> Optional[Order]:
        result = await self.db.execute(
            select(Order).options(joinedload(Order.items)).where(Order.id == order_id)
        )
        return result.unique().scalar_one_or_none()

    async def find_by_user(self, user_id: UUID, limit: int = 20, offset: int = 0) -> List[Order]:
        result = await self.db.execute(
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().unique().all())

    async def update_status(self, order_id: UUID, status: OrderStatus) -> Optional[Order]:
        from datetime import datetime
        await self.db.execute(
            update(Order).where(Order.id == order_id).values(status=status, updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return await self.find_by_id(order_id)
