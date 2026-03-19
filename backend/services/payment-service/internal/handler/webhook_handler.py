"""
Webhook handler for Stripe events.

LEARNING NOTES:
- Webhooks are HTTP callbacks — Stripe sends events to YOUR server.
- You MUST verify the signature to prevent attackers from sending fake events.
- The webhook secret is shared between you and Stripe and used for HMAC signing.
"""

from fastapi import APIRouter, HTTPException, Request

from internal.provider.stripe_client import StripeClient

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Receive and process Stripe webhook events."""
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")

    # Verify signature
    if not StripeClient.verify_webhook_signature(payload.decode(), signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Parse event
    try:
        event = StripeClient.construct_event(payload.decode())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type", "unknown")

    # Handle different event types
    if event_type == "payment_intent.succeeded":
        # Update payment status in DB
        pass
    elif event_type == "payment_intent.payment_failed":
        pass
    elif event_type == "charge.refunded":
        pass

    return {"received": True, "type": event_type}
