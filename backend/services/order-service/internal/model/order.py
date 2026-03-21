"""
Order model — tracks order lifecycle.

LEARNING NOTES:
- An Order has a status that follows a state machine:
  PENDING → CONFIRMED → SHIPPED → DELIVERED (or CANCELLED at any point before SHIPPED).
- Using an Enum column ensures only valid statuses are stored.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.PENDING)
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)
    shipping_address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Order(id={self.id}, status={self.status}, total={self.total_amount})>"
