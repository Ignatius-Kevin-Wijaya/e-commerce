"""Carrier quote handlers."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from internal.service.carrier_service import CarrierService

router = APIRouter(prefix="/mock-carriers", tags=["Mock Carriers"])


class CarrierQuoteRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=64)
    destination_zone: Literal["domestic", "regional", "remote"] = "domestic"
    priority: Literal["standard", "express"] = "standard"
    total_weight_grams: int = Field(..., ge=50, le=100000)


class CarrierQuoteResponse(BaseModel):
    carrier: str
    service_level: str
    amount: float
    currency: str
    estimated_days: int
    observed_delay_ms: int


@router.post("/{carrier}/quote", response_model=CarrierQuoteResponse)
async def quote(carrier: str, body: CarrierQuoteRequest):
    try:
        return await CarrierService().quote(carrier, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
