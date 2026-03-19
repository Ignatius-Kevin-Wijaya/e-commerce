"""
Product repository — database access for products and categories.
"""

import math
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from internal.model.category import Category
from internal.model.product import Product
from internal.utils.pagination import PaginatedResponse, PaginationParams


class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Products ─────────────────────────────────────────────

    async def find_products(
        self,
        pagination: PaginationParams,
        category_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> PaginatedResponse:
        """List products with pagination, optional filtering by category and search."""
        query = select(Product).where(Product.is_deleted == False)  # noqa: E712

        if category_id:
            query = query.where(Product.category_id == category_id)
        if search:
            query = query.where(Product.name.ilike(f"%{search}%"))

        # Count total matching
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Fetch page
        query = query.options(joinedload(Product.category))
        query = query.offset(pagination.offset).limit(pagination.page_size)
        query = query.order_by(Product.created_at.desc())

        result = await self.db.execute(query)
        items = result.scalars().unique().all()

        return PaginatedResponse(
            items=list(items),
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=math.ceil(total / pagination.page_size) if pagination.page_size else 0,
        )

    async def find_by_id(self, product_id: UUID) -> Optional[Product]:
        result = await self.db.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(Product.id == product_id, Product.is_deleted == False)  # noqa: E712
        )
        return result.scalar_one_or_none()

    async def create(self, product: Product) -> Product:
        self.db.add(product)
        await self.db.commit()
        await self.db.refresh(product)
        return product

    async def update_product(self, product_id: UUID, **kwargs) -> Optional[Product]:
        from datetime import datetime
        await self.db.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(**kwargs, updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return await self.find_by_id(product_id)

    async def soft_delete(self, product_id: UUID) -> bool:
        result = await self.db.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(is_deleted=True)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def update_stock(self, product_id: UUID, quantity_change: int) -> Optional[Product]:
        """Atomically change stock. Use negative for decrements."""
        product = await self.find_by_id(product_id)
        if not product:
            return None
        new_stock = product.stock + quantity_change
        if new_stock < 0:
            return None  # Not enough stock
        return await self.update_product(product_id, stock=new_stock)

    # ── Categories ───────────────────────────────────────────

    async def find_all_categories(self) -> List[Category]:
        result = await self.db.execute(select(Category).order_by(Category.name))
        return list(result.scalars().all())

    async def find_category_by_id(self, category_id: int) -> Optional[Category]:
        result = await self.db.execute(select(Category).where(Category.id == category_id))
        return result.scalar_one_or_none()

    async def create_category(self, category: Category) -> Category:
        self.db.add(category)
        await self.db.commit()
        await self.db.refresh(category)
        return category
