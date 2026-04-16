"""Business logic for aggregating shipping quotes."""

import uuid
from typing import Any

from internal.client.carrier_client import CarrierClient, CarrierClientError


class ShippingQuoteError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ShippingRateService:
    def __init__(self, carrier_client: CarrierClient):
        self.carrier_client = carrier_client

    @staticmethod
    def _total_weight_grams(items: list[dict[str, Any]]) -> int:
        return sum(item["weight_grams"] * item["quantity"] for item in items)

    async def get_quotes(self, request: dict[str, Any]) -> dict[str, Any]:
        items = request.get("items") or []
        if not items:
            raise ShippingQuoteError("At least one item is required")

        total_weight_grams = self._total_weight_grams(items)
        if total_weight_grams <= 0:
            raise ShippingQuoteError("Total package weight must be positive")

        request_id = str(uuid.uuid4())
        carrier_payload = {
            "request_id": request_id,
            "destination_zone": request["destination_zone"],
            "priority": request["priority"],
            "total_weight_grams": total_weight_grams,
        }

        try:
            quotes = await self.carrier_client.fetch_quotes(carrier_payload)
        except CarrierClientError as exc:
            raise ShippingQuoteError(str(exc), 503)

        quotes = sorted(quotes, key=lambda quote: (quote["amount"], quote["estimated_days"]))
        cheapest = min(quotes, key=lambda quote: quote["amount"])
        fastest = min(quotes, key=lambda quote: (quote["estimated_days"], quote["observed_delay_ms"]))

        return {
            "request_id": request_id,
            "destination_zone": request["destination_zone"],
            "priority": request["priority"],
            "total_weight_grams": total_weight_grams,
            "quote_count": len(quotes),
            "quotes": quotes,
            "recommended": {
                "cheapest_carrier": cheapest["carrier"],
                "fastest_carrier": fastest["carrier"],
            },
        }
