"""
Product & Category SQLAlchemy models.

LEARNING NOTES:
- Product has a foreign key to Category (many-to-one relationship).
- We use DECIMAL for prices — NEVER use float for money! Floats have rounding errors.
- `is_deleted` implements "soft delete" — we never truly remove products (audit trail).
- `stock` tracks inventory count.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    products = relationship("Product", back_populates="category")

    def __repr__(self):
        return f"<Category(id={self.id}, name={self.name})>"
