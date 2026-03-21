"""Order item model — individual line items within an order."""

import uuid
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import relationship

from internal.model.order import Base


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Uuid(as_uuid=True), nullable=False)
    product_name = Column(String(255), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")

    @property
    def subtotal(self):
        return self.price * self.quantity

    def __repr__(self):
        return f"<OrderItem(product={self.product_name}, qty={self.quantity})>"
