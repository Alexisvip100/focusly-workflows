from typing import Any
import stripe
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.user.domain.entities.user import User

stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_customer(self, user: User) -> str:
        """
        Obtiene el stripeCustomerId del usuario en la base de datos o
        crea un nuevo Customer en Stripe y lo asocia al usuario en Postgres.
        """
        if user.stripeCustomerId:
            # pyrefly: ignore [bad-return]
            return user.stripeCustomerId

        try:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.name or user.email,
                metadata={
                    "user_id": user.id,
                },
            )
            user.stripeCustomerId = customer.id
            await self.db.commit()
            await self.db.refresh(user)
            return customer.id
        except stripe.StripeError as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Error al crear cliente en Stripe: {str(e)}",
            )

    async def create_subscription(
        self,
        user: User,
        price_id: str,
        plan_name: str = "pro_monthly",
    ) -> dict[str, Any]:
        """
        Inicia una suscripción recurrente para el usuario autenticado.

        Crea una suscripción en estado 'incomplete' y devuelve el 'client_secret'.
        El frontend de React usa este 'client_secret' con Stripe Payment Element para que
        el usuario pague con tarjeta, Apple Pay, Google Pay, etc.

        Configuración clave:
        - payment_behavior="default_incomplete": Espera a que el frontend confirme el pago.
        - save_default_payment_method="on_subscription": Guarda la tarjeta/método usado
          como el predeterminado de la suscripción, asegurando que los siguientes meses
          Stripe cobre automáticamente a esa misma forma de pago sin intervención del usuario.
        """
        customer_id = await self.get_or_create_customer(user)

        # Evitar crear suscripciones duplicadas si el usuario ya tiene una activa
        if user.stripeSubscriptionId:
            try:
                existing_sub = stripe.Subscription.retrieve(user.stripeSubscriptionId)
                if existing_sub.status in ("active", "trialing"):
                    raise HTTPException(
                        status_code=400,
                        detail="Ya tienes una suscripción activa.",
                    )
            except stripe.InvalidRequestError:
                # Si el ID no existe en Stripe (ej. borrado en test mode), continuamos
                pass

        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=[
                    "latest_invoice.confirmation_secret",
                    "latest_invoice.payment_intent",
                    "pending_setup_intent",
                ],
                metadata={
                    "user_id": user.id,
                    "plan_name": plan_name,
                },
            )

            # Extraer el client_secret de la primera factura
            latest_invoice: Any = subscription.latest_invoice
            client_secret = None

            # 1. API Stripe moderna (2025+ Basil): confirmation_secret
            confirmation_secret = getattr(latest_invoice, "confirmation_secret", None)
            if confirmation_secret:
                client_secret = (
                    confirmation_secret.get("client_secret")
                    if hasattr(confirmation_secret, "get")
                    else getattr(confirmation_secret, "client_secret", None)
                )

            # 2. Fallback para versiones previas: payment_intent
            if not client_secret:
                payment_intent = getattr(latest_invoice, "payment_intent", None)
                if payment_intent:
                    client_secret = (
                        payment_intent.get("client_secret")
                        if hasattr(payment_intent, "get")
                        else getattr(payment_intent, "client_secret", None)
                    )

            # 3. Fallback para SetupIntent
            if not client_secret:
                pending_setup = getattr(subscription, "pending_setup_intent", None)
                if pending_setup:
                    client_secret = (
                        pending_setup.get("client_secret")
                        if hasattr(pending_setup, "get")
                        else getattr(pending_setup, "client_secret", None)
                    )

            if not client_secret:
                raise HTTPException(
                    status_code=500,
                    detail="No se pudo obtener el client_secret de la factura de Stripe.",
                )

            # Guardar el ID de suscripción en el usuario tras verificar el client_secret
            user.stripeSubscriptionId = subscription.id
            await self.db.commit()

            return {
                "subscription_id": subscription.id,
                "client_secret": client_secret,
                "customer_id": customer_id,
                "status": subscription.status,
            }
        except stripe.StripeError as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Error al iniciar suscripción en Stripe: {str(e)}",
            )

    async def create_customer_portal(self, user: User) -> str:
        """
        Genera la URL del Customer Portal oficial de Stripe.
        Permite al usuario cambiar su tarjeta guardada, ver facturas pasadas o cancelar el plan.
        """
        customer_id = await self.get_or_create_customer(user)
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=f"{settings.FRONTEND_URL}/settings/billing",
            )
            return portal_session.url
        except stripe.StripeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error al generar sesión del portal de cliente: {str(e)}",
            )

    async def cancel_subscription(
        self, user: User, cancel_at_period_end: bool = True
    ) -> dict[str, Any]:
        """
        Cancela la suscripción del usuario.
        cancel_at_period_end=True permite al usuario conservar el acceso Pro hasta el final
        del ciclo mensual pagado.
        """
        if not user.stripeSubscriptionId:
            raise HTTPException(
                status_code=400,
                detail="El usuario no tiene ninguna suscripción activa para cancelar.",
            )

        try:
            if cancel_at_period_end:
                sub = stripe.Subscription.modify(
                    user.stripeSubscriptionId,
                    cancel_at_period_end=True,
                )
            else:
                sub = stripe.Subscription.cancel(user.stripeSubscriptionId)
                user.subscriptionStatus = "free"
                user.stripeSubscriptionId = None
                await self.db.commit()

            return {
                "subscription_id": sub.id,
                "status": sub.status,
                "cancel_at_period_end": sub.cancel_at_period_end,
            }
        except stripe.StripeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error al cancelar suscripción: {str(e)}",
            )
