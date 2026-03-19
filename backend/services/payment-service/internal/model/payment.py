"""
Payment model with idempotency key support.

LEARNING NOTES:
- The idempotency_key ensures we never charge a customer twice for the same payment.
- If the same idempotency_key is sent again, we return the existing payment instead
  of creating a new one. This is how Stripe, PayPal, etc. work.
- Payment status: PENDING → PROCESSING → SUCCESS / FAILED
"""

import uuid
from datetime import datetime
import enum

from sqlalchemy import Column, DateTime, Enum, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    provider = Column(String(50), nullable=False, default="stripe")
    provider_payment_id = Column(String(255), nullable=True)  # Stripe PaymentIntent ID
    idempotency_key = Column(String(255), unique=True, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Payment(id={self.id}, order={self.order_id}, status={self.status})>"
