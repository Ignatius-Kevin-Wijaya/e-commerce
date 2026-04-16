"""Deterministic delayed carrier quote generation."""

import asyncio
import hashlib
import os

CARRIER_DELAY_SCALE = float(os.getenv("CARRIER_DELAY_SCALE", "1.0"))

_CARRIER_CONFIG = {
    "fastship": {"base_delay_ms": 220, "zone_multiplier": {"domestic": 0, "regional": 90, "remote": 180}, "price_multiplier": 1.45, "days": {"domestic": 1, "regional": 2, "remote": 4}},
    "ecopost": {"base_delay_ms": 360, "zone_multiplier": {"domestic": 40, "regional": 150, "remote": 260}, "price_multiplier": 1.0, "days": {"domestic": 2, "regional": 4, "remote": 6}},
    "globex": {"base_delay_ms": 520, "zone_multiplier": {"domestic": 60, "regional": 190, "remote": 320}, "price_multiplier": 1.18, "days": {"domestic": 3, "regional": 5, "remote": 8}},
}


class CarrierService:
    @staticmethod
    def _jitter_ms(request_id: str, carrier: str) -> int:
        digest = hashlib.sha256(f"{request_id}:{carrier}".encode()).hexdigest()
        return int(digest[:4], 16) % 90

    async def quote(self, carrier: str, request: dict) -> dict:
        if carrier not in _CARRIER_CONFIG:
            raise ValueError(f"Unknown carrier: {carrier}")

        config = _CARRIER_CONFIG[carrier]
        zone = request["destination_zone"]
        delay_ms = int(
            (config["base_delay_ms"] + config["zone_multiplier"][zone] + self._jitter_ms(request["request_id"], carrier))
            * CARRIER_DELAY_SCALE
        )
        if request["priority"] == "express":
            delay_ms = max(int(delay_ms * 0.8), 80)

        await asyncio.sleep(delay_ms / 1000.0)

        total_weight_grams = request["total_weight_grams"]
        weight_kg = total_weight_grams / 1000.0
        amount = round((4.75 + weight_kg * 0.85) * config["price_multiplier"], 2)
        if zone == "remote":
            amount = round(amount + 4.50, 2)
        if request["priority"] == "express":
            amount = round(amount + 3.25, 2)

        return {
            "carrier": carrier,
            "service_level": request["priority"],
            "amount": amount,
            "currency": "USD",
            "estimated_days": max(config["days"][zone] - (1 if request["priority"] == "express" else 0), 1),
            "observed_delay_ms": delay_ms,
        }
