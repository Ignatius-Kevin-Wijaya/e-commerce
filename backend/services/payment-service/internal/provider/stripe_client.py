"""
Simulated Stripe payment provider.

LEARNING NOTES:
- This is a MOCK — it simulates Stripe's API without needing a real API key.
- In production, you'd use the real 'stripe' Python SDK.
- The mock randomly succeeds/fails to simulate real-world behavior.
- It demonstrates the pattern: create payment intent → confirm → webhook callback.
"""

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from typing import Optional

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_fake_key")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_fake_secret")


@dataclass
class PaymentIntent:
    """Simulates a Stripe PaymentIntent object."""
    id: str
    amount: int  # in cents
    currency: str
    status: str  # "succeeded", "requires_payment_method", "failed"
    client_secret: str


class StripeClient:
    """Simulated Stripe client for learning purposes."""

    def __init__(self):
        self.secret_key = STRIPE_SECRET_KEY

    async def create_payment_intent(
        self,
        amount_cents: int,
        currency: str = "usd",
        idempotency_key: Optional[str] = None,
    ) -> PaymentIntent:
        """
        Simulate creating a Stripe PaymentIntent.
        In reality, this would call Stripe's API.
        """
        intent_id = f"pi_{uuid.uuid4().hex[:24]}"
        client_secret = f"{intent_id}_secret_{uuid.uuid4().hex[:16]}"

        # Simulate: amounts over $999.99 (99999 cents) "fail" for testing
        if amount_cents > 99999:
            return PaymentIntent(
                id=intent_id,
                amount=amount_cents,
                currency=currency,
                status="failed",
                client_secret=client_secret,
            )

        return PaymentIntent(
            id=intent_id,
            amount=amount_cents,
            currency=currency,
            status="succeeded",
            client_secret=client_secret,
        )

    @staticmethod
    def verify_webhook_signature(payload: str, signature: str) -> bool:
        """
        Verify that a webhook came from Stripe (not an attacker).
        In production, Stripe signs webhooks with HMAC-SHA256.
        """
        expected = hmac.new(
            STRIPE_WEBHOOK_SECRET.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def construct_event(payload: str) -> dict:
        """Parse a webhook payload into an event dict."""
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise ValueError("Invalid webhook payload")
