"""
Product service — business logic layer.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from internal.model.category import Category
from internal.model.product import Product
from internal.repository.product_repository import ProductRepository
from internal.utils.pagination import PaginatedResponse, PaginationParams


class ProductServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ProductService:
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    async def list_products(
        self,
        page: int = 1,
        page_size: int = 20,
        category_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> PaginatedResponse:
        pagination = PaginationParams(page=page, page_size=page_size)
        return await self.repo.find_products(pagination, category_id, search)

    async def get_product(self, product_id: UUID) -> Product:
        product = await self.repo.find_by_id(product_id)
        if not product:
            raise ProductServiceError("Product not found", 404)
        return product

    async def create_product(
        self,
        name: str,
        description: Optional[str],
        price: Decimal,
        stock: int,
        category_id: Optional[int] = None,
        image_url: Optional[str] = None,
    ) -> Product:
        if price <= 0:
            raise ProductServiceError("Price must be positive")
        if stock < 0:
            raise ProductServiceError("Stock cannot be negative")

        # Verify category exists
        if category_id:
            cat = await self.repo.find_category_by_id(category_id)
            if not cat:
                raise ProductServiceError("Category not found", 404)

        product = Product(
            name=name,
            description=description,
            price=price,
            stock=stock,
            category_id=category_id,
            image_url=image_url,
        )
        return await self.repo.create(product)

    async def update_product(self, product_id: UUID, **kwargs) -> Product:
        existing = await self.repo.find_by_id(product_id)
        if not existing:
            raise ProductServiceError("Product not found", 404)
        updated = await self.repo.update_product(product_id, **kwargs)
        return updated

    async def decrease_stock(self, product_id: UUID, quantity: int) -> Product:
        if quantity <= 0:
            raise ProductServiceError("Quantity to decrease must be positive", 400)
        
        updated = await self.repo.update_stock(product_id, -quantity)
        if not updated:
            product = await self.repo.find_by_id(product_id)
            if not product:
                raise ProductServiceError("Product not found", 404)
            else:
                raise ProductServiceError("Insufficient stock", 400)
        return updated

    async def increase_stock(self, product_id: UUID, quantity: int) -> Product:
        if quantity <= 0:
            raise ProductServiceError("Quantity to increase must be positive", 400)
        
        updated = await self.repo.update_stock(product_id, quantity)
        if not updated:
            raise ProductServiceError("Product not found", 404)
        return updated

    async def delete_product(self, product_id: UUID) -> None:
        success = await self.repo.soft_delete(product_id)
        if not success:
            raise ProductServiceError("Product not found", 404)

    async def list_categories(self):
        return await self.repo.find_all_categories()

    async def create_category(self, name: str, description: Optional[str] = None) -> Category:
        category = Category(name=name, description=description)
        return await self.repo.create_category(category)
