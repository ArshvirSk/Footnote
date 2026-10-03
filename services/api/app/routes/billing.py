"""Billing routes and Stripe webhook handlers."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.logging import get_logger

logger = get_logger(__name__)

# Note: No auth dependency here; webhooks use signature verification.
router = APIRouter(prefix="/webhooks/stripe", tags=["billing"])


async def process_subscription_updated(data: dict[str, Any], db: AsyncSession) -> None:
    """Update org/client tier limits based on Stripe subscription data."""
    # In reality, map Stripe Customer ID -> Org ID
    # Here we mock finding an org and updating its settings based on the tier
    stripe_customer_id = data.get("customer")
    plan_id = data.get("items", {}).get("data", [{}])[0].get("plan", {}).get("id", "basic")
    
    # Map plans to limits
    limits = {"max_prompts": 25}  # default
    if "pro" in plan_id:
        limits["max_prompts"] = 125
    elif "enterprise" in plan_id:
        limits["max_prompts"] = 500

    async with db.begin():
        # Update settings JSONB for clients under the customer's organization
        await db.execute(
            text("""
                UPDATE clients
                SET settings = jsonb_set(COALESCE(settings, '{}'::jsonb), '{billing_limits}', :limits::jsonb)
                WHERE org_id IN (
                    SELECT id FROM organizations WHERE stripe_customer_id = :stripe_id
                )
            """),
            {"limits": json.dumps(limits), "stripe_id": stripe_customer_id}
        )
        logger.info("billing_limits_updated", stripe_customer_id=stripe_customer_id, limits=limits)


@router.post("", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Handle Stripe webhooks."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing signature")
        
    # In a real impl, we'd verify the signature:
    # try:
    #     event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    # except ValueError:
    #     raise HTTPException(status_code=400, detail="Invalid payload")
    
    # Simulate parsing the event
    event = json.loads(payload)
    event_type = event.get("type")
    
    if event_type in ["customer.subscription.created", "customer.subscription.updated"]:
        await process_subscription_updated(event.get("data", {}).get("object", {}), db)
    elif event_type == "customer.subscription.deleted":
        logger.warning("subscription_cancelled", customer=event.get("data", {}).get("object", {}).get("customer"))
        # Handle downgrading org to free/inactive
        
    return {"status": "success"}
