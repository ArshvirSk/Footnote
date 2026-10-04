"""Billing routes and Stripe webhook handlers.

Signature verification uses Stripe's standard scheme:
HMAC-SHA256(secret, "{timestamp}.{payload}") compared to the v1= claim.
The webhook is disabled unless STRIPE_WEBHOOK_SECRET is configured.
"""

import hashlib
import hmac
import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Webhooks use signature verification, not user auth.
router = APIRouter(prefix="/webhooks/stripe", tags=["billing"])

STRIPE_SIGNATURE_TOLERANCE_SECONDS = 300


def verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify a Stripe-Signature header (t=...,v1=...) against the raw payload."""
    try:
        parts = dict(part.split("=", 1) for part in sig_header.split(","))
        timestamp = parts["t"]
        provided = parts["v1"]
    except (KeyError, ValueError):
        return False

    try:
        if abs(time.time() - int(timestamp)) > STRIPE_SIGNATURE_TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False

    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


async def process_subscription_updated(data: dict[str, Any], db: AsyncSession) -> None:
    """Update org billing limits based on Stripe subscription data."""
    stripe_customer_id = data.get("customer")
    plan_id = data.get("items", {}).get("data", [{}])[0].get("plan", {}).get("id", "basic")

    limits = {"max_prompts": 25}  # default
    if "pro" in plan_id:
        limits["max_prompts"] = 125
    elif "enterprise" in plan_id:
        limits["max_prompts"] = 500

    await db.execute(
        text(
            """
            UPDATE clients
            SET settings = jsonb_set(COALESCE(settings, '{}'::jsonb), '{billing_limits}', CAST(:limits AS jsonb))
            WHERE org_id IN (
                SELECT id FROM organizations WHERE stripe_customer_id = :stripe_id
            )
            """
        ),
        {"limits": json.dumps(limits), "stripe_id": stripe_customer_id},
    )
    await db.commit()
    logger.info("billing_limits_updated", stripe_customer_id=stripe_customer_id, limits=limits)


@router.post("", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Handle Stripe webhooks (signature-verified)."""
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not verify_stripe_signature(payload, sig_header, settings.stripe_webhook_secret):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload") from exc

    event_type = event.get("type")

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        await process_subscription_updated(event.get("data", {}).get("object", {}), db)
    elif event_type == "customer.subscription.deleted":
        logger.warning(
            "subscription_cancelled",
            customer=event.get("data", {}).get("object", {}).get("customer"),
        )

    return {"status": "success"}
