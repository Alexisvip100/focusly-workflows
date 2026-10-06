import logging
from typing import Any

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.modules.billing.services.stripe_service import StripeService
from app.modules.user.domain.entities.user import User
from app.routes.common import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["Billing"])


class CancelSubscriptionRequest(BaseModel):
    cancel_at_period_end: bool = True


async def _current_user(user_id: str, db: AsyncSession) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.get("/status")
async def get_billing_status(
    refresh: bool = False,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The user's plan and free AI usage. refresh=true reads the subscription
    from Stripe first (after paying, before the webhook may have arrived)."""
    user = await _current_user(current_user_id, db)
    return await StripeService(db).get_status(user, refresh=refresh)


@router.post("/subscribe")
async def create_subscription(
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Starts the Pro subscription; returns the client_secret the Payment
    Element confirms. The price is the server's (STRIPE_PRICE_ID_PRO): any
    price the client sends is ignored."""
    user = await _current_user(current_user_id, db)
    return await StripeService(db).create_subscription(user)


@router.post("/portal")
async def get_customer_portal(
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user = await _current_user(current_user_id, db)
    return {"url": await StripeService(db).create_customer_portal(user)}


@router.post("/cancel")
async def cancel_subscription(
    body: CancelSubscriptionRequest | None = None,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await _current_user(current_user_id, db)
    return await StripeService(db).cancel_subscription(
        user,
        cancel_at_period_end=body.cancel_at_period_end if body else True,
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Stripe's notifications (payments, renewals, failures, cancellations).
    Only signed events are accepted."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook no configurado")
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Falta la firma de Stripe")

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Firma de webhook inválida")

    try:
        await StripeService(db).handle_event(event)
    except Exception:
        # A 5xx makes Stripe retry the event later.
        logger.exception("Stripe webhook %s failed", getattr(event, "type", "?"))
        raise HTTPException(status_code=500, detail="Webhook processing failed")
    return {"received": True}
