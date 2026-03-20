"""
Product HTTP handlers — CRUD routes for products and categories.
"""

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from internal.repository.product_repository import ProductRepository
from internal.service.product_service import ProductService, ProductServiceError

router = APIRouter(tags=["Products"])


# ── Schemas ──────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    price: Decimal = Field(..., gt=0)
    stock: int = Field(..., ge=0)
    category_id: Optional[int] = None
    image_url: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    stock: Optional[int] = None
    category_id: Optional[int] = None
    image_url: Optional[str] = None


class DecreaseStockRequest(BaseModel):
    quantity: int = Field(..., gt=0)


class IncreaseStockRequest(BaseModel):
    quantity: int = Field(..., gt=0)


class ProductResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    price: float
    stock: int
    category_id: Optional[int]
    category_name: Optional[str] = None
    image_url: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]

    class Config:
        from_attributes = True


class PaginatedProductResponse(BaseModel):
    items: List[ProductResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Dependencies ─────────────────────────────────────────────

async def get_product_service(request: Request) -> ProductService:
    db: AsyncSession = request.state.db
    repo = ProductRepository(db)
    return ProductService(repo)


def product_to_response(product) -> ProductResponse:
    return ProductResponse(
        id=str(product.id),
        name=product.name,
        description=product.description,
        price=float(product.price),
        stock=product.stock,
        category_id=product.category_id,
        category_name=product.category.name if product.category else None,
        image_url=product.image_url,
        created_at=product.created_at.isoformat(),
        updated_at=product.updated_at.isoformat(),
    )


# ── Product Routes ───────────────────────────────────────────

@router.get("/products", response_model=PaginatedProductResponse)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    service: ProductService = Depends(get_product_service),
):
    """List products with pagination and optional filtering."""
    result = await service.list_products(page, page_size, category_id, search)
    return PaginatedProductResponse(
        items=[product_to_response(p) for p in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    service: ProductService = Depends(get_product_service),
):
    """Get a single product by ID."""
    try:
        product = await service.get_product(product_id)
        return product_to_response(product)
    except ProductServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    body: ProductCreate,
    service: ProductService = Depends(get_product_service),
):
    """Create a new product (admin only in production)."""
    try:
        product = await service.create_product(
            name=body.name,
            description=body.description,
            price=body.price,
            stock=body.stock,
            category_id=body.category_id,
            image_url=body.image_url,
        )
        return product_to_response(product)
    except ProductServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    body: ProductUpdate,
    service: ProductService = Depends(get_product_service),
):
    """Update an existing product."""
    try:
        updates = body.model_dump(exclude_unset=True)
        product = await service.update_product(product_id, **updates)
        return product_to_response(product)
    except ProductServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(
    product_id: UUID,
    service: ProductService = Depends(get_product_service),
):
    """Soft-delete a product."""
    try:
        await service.delete_product(product_id)
    except ProductServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.patch("/products/{product_id}/stock/decrease", response_model=ProductResponse)
async def decrease_stock(
    product_id: UUID,
    body: DecreaseStockRequest,
    service: ProductService = Depends(get_product_service),
):
    """Decrease the stock of a product."""
    try:
        product = await service.decrease_stock(product_id, body.quantity)
        return product_to_response(product)
    except ProductServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.patch("/products/{product_id}/stock/increase", response_model=ProductResponse)
async def increase_stock(
    product_id: UUID,
    body: IncreaseStockRequest,
    service: ProductService = Depends(get_product_service),
):
    """Increase the stock of a product (e.g. after order cancellation)."""
    try:
        product = await service.increase_stock(product_id, body.quantity)
        return product_to_response(product)
    except ProductServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ── Category Routes ──────────────────────────────────────────

@router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(service: ProductService = Depends(get_product_service)):
    """List all categories."""
    categories = await service.list_categories()
    return [CategoryResponse(id=c.id, name=c.name, description=c.description) for c in categories]


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    body: CategoryCreate,
    service: ProductService = Depends(get_product_service),
):
    """Create a new category."""
    try:
        category = await service.create_category(body.name, body.description)
        return CategoryResponse(id=category.id, name=category.name, description=category.description)
    except ProductServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
