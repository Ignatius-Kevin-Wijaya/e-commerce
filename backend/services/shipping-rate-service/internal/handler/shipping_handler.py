"""Shipping quote HTTP handlers."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from internal.client.carrier_client import CarrierClient
from internal.service.shipping_service import ShippingQuoteError, ShippingRateService

router = APIRouter(prefix="/shipping", tags=["Shipping"])


class ShippingItemRequest(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(1, ge=1, le=20)
    weight_grams: int = Field(..., ge=50, le=10000)


class ShippingQuoteRequest(BaseModel):
    destination_zone: Literal["domestic", "regional", "remote"] = "domestic"
    priority: Literal["standard", "express"] = "standard"
    items: list[ShippingItemRequest] = Field(..., min_length=1, max_length=8)


class CarrierQuoteResponse(BaseModel):
    carrier: str
    service_level: str
    amount: float
    currency: str
    estimated_days: int
    observed_delay_ms: int


class RecommendedQuoteResponse(BaseModel):
    cheapest_carrier: str
    fastest_carrier: str


class ShippingQuoteResponse(BaseModel):
    request_id: str
    destination_zone: str
    priority: str
    total_weight_grams: int
    quote_count: int
    quotes: list[CarrierQuoteResponse]
    recommended: RecommendedQuoteResponse


def get_shipping_service() -> ShippingRateService:
    return ShippingRateService(CarrierClient())


@router.post("/quotes", response_model=ShippingQuoteResponse)
async def get_shipping_quotes(
    body: ShippingQuoteRequest,
    service: ShippingRateService = Depends(get_shipping_service),
):
    try:
        return await service.get_quotes(body.model_dump())
    except ShippingQuoteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
