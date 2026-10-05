from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import stripe

from app.database import get_db
from app.config import settings
from app.routes.common import get_current_user_id
from app.modules.user.domain.entities.user import User
from app.modules.billing.services.stripe_service import StripeService

router = APIRouter(prefix="/api/billing", tags=["Billing"])


class SubscribeRequest(BaseModel):
    price_id: str
    plan_name: str = "pro_monthly"


class CancelSubscriptionRequest(BaseModel):
    cancel_at_period_end: bool = True


@router.post("/subscribe")
async def create_subscription(
    body: SubscribeRequest,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Inicia una suscripción recurrente para el usuario logueado.
    Devuelve el client_secret para que el frontend confirme el pago con Payment Element.
    """
    user = await db.get(User, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    service = StripeService(db)
    return await service.create_subscription(
        user=user,
        price_id=body.price_id,
        plan_name=body.plan_name,
    )


@router.post("/portal")
async def get_customer_portal(
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Devuelve la URL del portal oficial de Stripe para que el usuario gestione
    su tarjeta, vea sus recibos o cancele su suscripción.
    """
    user = await db.get(User, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    service = StripeService(db)
    portal_url = await service.create_customer_portal(user)
    return {"url": portal_url}


@router.post("/cancel")
async def cancel_subscription(
    body: CancelSubscriptionRequest = CancelSubscriptionRequest(),
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Cancela la suscripción del usuario logueado.
    """
    user = await db.get(User, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    service = StripeService(db)
    return await service.cancel_subscription(
        user=user, cancel_at_period_end=body.cancel_at_period_end
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Webhook que recibe los eventos de Stripe de forma segura y
    actualiza el estado de la suscripción en la base de datos de Focusly.
    """
    payload = await request.body()

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500, detail="STRIPE_WEBHOOK_SECRET no configurado"
        )

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Firma de webhook inválida")

    event_type = event["type"]
    data = event["data"]["object"]

    # 1. Pago de factura completado (primer pago o renovación mensual automática)
    if event_type == "invoice.payment_succeeded":
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")

        # Buscar usuario por stripeCustomerId
        stmt = select(User).where(User.stripeCustomerId == customer_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.subscriptionStatus = "pro"
            if subscription_id:
                user.stripeSubscriptionId = subscription_id
            await db.commit()

    # 2. Suscripción cancelada o vencida
    elif event_type in (
        "customer.subscription.deleted",
        "customer.subscription.paused",
    ):
        customer_id = data.get("customer")

        stmt = select(User).where(User.stripeCustomerId == customer_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.subscriptionStatus = "free"
            user.stripeSubscriptionId = None
            await db.commit()

    return {"status": "success"}
