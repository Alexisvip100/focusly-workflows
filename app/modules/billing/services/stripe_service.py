import logging
import time
from typing import Any

import stripe
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.modules.billing.plans import (
    ACCESS_STATUSES,
    FREE,
    FREE_AI_MESSAGE_LIMIT,
    PRO,
    is_pro,
)
from app.modules.user.domain.entities.user import User

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

# Subscriptions that are over for good: the user can start a new one.
ENDED_STATUSES = frozenset({"canceled", "incomplete_expired"})

GENERIC_STRIPE_ERROR = "No se pudo completar la operación con Stripe. Intenta de nuevo."

# The Pro price as shown on the plan cards, read from Stripe (so the page
# never disagrees with what's charged) and kept for an hour.
PRICE_CACHE_SECONDS = 3600
_price_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """A field from a Stripe object or a plain dict (tests).

    StripeObject has no .get() since stripe-python 13, only obj["key"]."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError):
        return default


def _id(value: Any) -> str | None:
    """An id from either a plain id or an expanded object."""
    if value is None or isinstance(value, str):
        return value
    return _get(value, "id")


def invoice_subscription_id(invoice: Any) -> str | None:
    # Since API 2025-03-31 the invoice's subscription lives under
    # parent.subscription_details; older versions had invoice.subscription.
    details = _get(_get(invoice, "parent"), "subscription_details")
    return _id(_get(details, "subscription")) or _id(_get(invoice, "subscription"))


def subscription_period_end(subscription: Any) -> int | None:
    # Since API 2025-03-31 the billing period lives on each item.
    items = _get(_get(subscription, "items"), "data") or []
    ends = [_get(item, "current_period_end") for item in items]
    ends = [end for end in ends if end]
    return max(ends) if ends else _get(subscription, "current_period_end")


def subscription_client_secret(subscription: Any) -> tuple[str | None, str | None]:
    """The secret the browser confirms the first payment with, and whether
    it belongs to a PaymentIntent ("payment") or a SetupIntent ("setup",
    e.g. a free trial)."""
    invoice = _get(subscription, "latest_invoice")
    secret = _get(_get(invoice, "confirmation_secret"), "client_secret")
    if secret:
        return secret, "payment"
    secret = _get(_get(subscription, "pending_setup_intent"), "client_secret")
    if secret:
        return secret, "setup"
    return None, None


def require_billing(*, price: bool = False) -> None:
    if not settings.STRIPE_SECRET_KEY or (price and not settings.STRIPE_PRICE_ID_PRO):
        raise HTTPException(
            status_code=503, detail="Los pagos no están configurados todavía."
        )


class StripeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Stripe calls (the SDK is blocking: keep it off the event loop) ──

    async def _retrieve_subscription(self, subscription_id: str) -> Any | None:
        """None when Stripe doesn't have it (e.g. deleted in test mode)."""
        try:
            return await run_in_threadpool(
                stripe.Subscription.retrieve, subscription_id
            )
        except stripe.InvalidRequestError as e:
            if getattr(e, "code", None) == "resource_missing":
                return None
            raise

    async def get_or_create_customer(self, user: User) -> str:
        if user.stripeCustomerId:
            return user.stripeCustomerId
        try:
            customer = await run_in_threadpool(
                stripe.Customer.create,
                email=user.email,
                name=user.name or user.email,
                metadata={"user_id": user.id},
                # A double click doesn't create two customers.
                idempotency_key=f"focusly-customer-{user.id}",
            )
        except stripe.StripeError:
            logger.exception("Stripe customer creation failed for %s", user.id)
            raise HTTPException(status_code=502, detail=GENERIC_STRIPE_ERROR)
        user.stripeCustomerId = customer.id
        await self.db.commit()
        return customer.id

    async def pro_price(self) -> dict[str, Any] | None:
        """{amount, currency, interval} of the Pro price, or None if unknown."""
        if not (settings.STRIPE_SECRET_KEY and settings.STRIPE_PRICE_ID_PRO):
            return None
        if (
            _price_cache["value"]
            and time.time() - _price_cache["at"] < PRICE_CACHE_SECONDS
        ):
            return _price_cache["value"]
        try:
            price = await run_in_threadpool(
                stripe.Price.retrieve, settings.STRIPE_PRICE_ID_PRO
            )
        except stripe.StripeError:
            logger.exception("Could not read the Pro price from Stripe")
            return _price_cache["value"]
        value = {
            "amount": _get(price, "unit_amount"),
            "currency": _get(price, "currency"),
            "interval": _get(_get(price, "recurring"), "interval"),
        }
        _price_cache.update(at=time.time(), value=value)
        return value

    # ── Plan state ──

    async def sync_subscription(self, user: User, subscription: Any) -> None:
        """Mirrors a Stripe subscription onto the user's plan. Stripe is the
        source of truth: the browser never decides who is Pro."""
        sub_id = _get(subscription, "id")
        status = _get(subscription, "status")

        if status in ACCESS_STATUSES:
            user.subscriptionStatus = PRO
            user.stripeSubscriptionId = sub_id
        elif sub_id == user.stripeSubscriptionId:
            # The user's own subscription stopped giving access.
            user.subscriptionStatus = FREE
            if status in ENDED_STATUSES:
                user.stripeSubscriptionId = None
        else:
            # An older, abandoned subscription: it must not downgrade the
            # user's current one.
            return
        await self.db.commit()

    async def get_status(self, user: User, refresh: bool = False) -> dict[str, Any]:
        subscription = None
        if refresh and user.stripeSubscriptionId and settings.STRIPE_SECRET_KEY:
            try:
                subscription = await self._retrieve_subscription(
                    user.stripeSubscriptionId
                )
                if subscription is None:
                    user.subscriptionStatus = FREE
                    user.stripeSubscriptionId = None
                    await self.db.commit()
                else:
                    await self.sync_subscription(user, subscription)
            except stripe.StripeError:
                # Stripe unreachable: answer with what we know.
                logger.exception("Could not refresh subscription for %s", user.id)

        used = user.aiMessagesUsed or 0
        return {
            "plan": PRO if is_pro(user) else FREE,
            "subscription_status": _get(subscription, "status"),
            "cancel_at_period_end": bool(_get(subscription, "cancel_at_period_end")),
            "current_period_end": subscription_period_end(subscription)
            if subscription
            else None,
            "ai_messages_used": used,
            "ai_messages_limit": FREE_AI_MESSAGE_LIMIT,
            "billing_enabled": bool(
                settings.STRIPE_SECRET_KEY and settings.STRIPE_PRICE_ID_PRO
            ),
            "pro_price": await self.pro_price(),
        }

    # ── Checkout ──

    async def create_customer_session(self, customer_id: str) -> str | None:
        """Lets the Payment Element show the cards the customer already saved
        with Focusly (e.g. coming back after cancelling). None if Stripe
        refuses: the checkout still works, just without them."""
        try:
            session = await run_in_threadpool(
                stripe.CustomerSession.create,
                customer=customer_id,
                components={
                    "payment_element": {
                        "enabled": True,
                        "features": {
                            "payment_method_redisplay": "enabled",
                            # "limited": saved for a past Focusly subscription.
                            # Not "unspecified": no consent on record.
                            "payment_method_allow_redisplay_filters": [
                                "always",
                                "limited",
                            ],
                            "payment_method_redisplay_limit": 3,
                            # Removing a card here would also take it off an
                            # active subscription (Stripe's advice): that's
                            # done in the Customer Portal.
                            "payment_method_remove": "disabled",
                            # The subscription already saves the card it's
                            # paid with (save_default_payment_method).
                            "payment_method_save": "disabled",
                        },
                    }
                },
            )
        except stripe.StripeError:
            logger.warning("Could not create a customer session for %s", customer_id)
            return None
        return session.client_secret

    async def create_subscription(self, user: User) -> dict[str, Any]:
        """Starts a Pro subscription in "incomplete" state and returns the
        secret the browser's Payment Element confirms the first payment with.
        The card is saved as the subscription's default, so Stripe charges
        it every month on its own."""
        require_billing(price=True)
        if is_pro(user):
            raise HTTPException(status_code=409, detail="Ya tienes Focusly Pro.")

        customer_id = await self.get_or_create_customer(user)

        if user.stripeSubscriptionId:
            current = await self._retrieve_subscription(user.stripeSubscriptionId)
            status = _get(current, "status")
            if status in ACCESS_STATUSES:
                # Paid, but the webhook hasn't arrived yet: don't charge twice.
                await self.sync_subscription(user, current)
                raise HTTPException(status_code=409, detail="Ya tienes Focusly Pro.")
            if status == "incomplete":
                # An abandoned checkout: cancel it so it can't be paid later
                # on top of the new one.
                try:
                    await run_in_threadpool(
                        stripe.Subscription.cancel, user.stripeSubscriptionId
                    )
                except stripe.StripeError:
                    logger.warning(
                        "Could not cancel stale subscription %s",
                        user.stripeSubscriptionId,
                    )

        try:
            subscription = await run_in_threadpool(
                stripe.Subscription.create,
                customer=customer_id,
                items=[{"price": settings.STRIPE_PRICE_ID_PRO}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.confirmation_secret", "pending_setup_intent"],
                metadata={"user_id": user.id, "plan": "pro_monthly"},
            )
        except stripe.StripeError:
            logger.exception("Stripe subscription creation failed for %s", user.id)
            raise HTTPException(status_code=502, detail=GENERIC_STRIPE_ERROR)

        client_secret, intent_type = subscription_client_secret(subscription)
        if not client_secret:
            logger.error("Subscription %s has no client secret", subscription.id)
            raise HTTPException(status_code=502, detail=GENERIC_STRIPE_ERROR)

        user.stripeSubscriptionId = subscription.id
        await self.db.commit()

        customer_session_secret = await self.create_customer_session(customer_id)
        items = _get(_get(subscription, "items"), "data") or []
        price = _get(items[0], "price") if items else None
        return {
            "subscription_id": subscription.id,
            "client_secret": client_secret,
            "intent_type": intent_type,
            "customer_session_client_secret": customer_session_secret,
            "status": subscription.status,
            "amount": _get(price, "unit_amount"),
            "currency": _get(price, "currency"),
            "interval": _get(_get(price, "recurring"), "interval"),
        }

    async def create_customer_portal(self, user: User) -> str:
        """Stripe's own page to change the card, see invoices or cancel."""
        require_billing()
        if not user.stripeCustomerId:
            raise HTTPException(
                status_code=400, detail="Todavía no tienes datos de facturación."
            )
        try:
            session = await run_in_threadpool(
                stripe.billing_portal.Session.create,
                customer=user.stripeCustomerId,
                return_url=f"{settings.FRONTEND_URL}/profile/billing",
            )
        except stripe.StripeError:
            logger.exception("Stripe portal session failed for %s", user.id)
            raise HTTPException(status_code=502, detail=GENERIC_STRIPE_ERROR)
        return session.url

    async def cancel_subscription(
        self, user: User, cancel_at_period_end: bool = True
    ) -> dict[str, Any]:
        """At period end by default: the user keeps Pro until the paid month ends."""
        require_billing()
        if not user.stripeSubscriptionId:
            raise HTTPException(
                status_code=400, detail="No tienes una suscripción activa."
            )
        try:
            if cancel_at_period_end:
                subscription = await run_in_threadpool(
                    stripe.Subscription.modify,
                    user.stripeSubscriptionId,
                    cancel_at_period_end=True,
                )
            else:
                subscription = await run_in_threadpool(
                    stripe.Subscription.cancel, user.stripeSubscriptionId
                )
        except stripe.StripeError:
            logger.exception("Stripe cancellation failed for %s", user.id)
            raise HTTPException(status_code=502, detail=GENERIC_STRIPE_ERROR)

        await self.sync_subscription(user, subscription)
        return {
            "subscription_id": subscription.id,
            "status": subscription.status,
            "cancel_at_period_end": bool(_get(subscription, "cancel_at_period_end")),
        }

    # ── Webhooks ──

    async def _user_for(self, subscription: Any) -> User | None:
        customer_id = _id(_get(subscription, "customer"))
        if customer_id:
            result = await self.db.execute(
                select(User).where(User.stripeCustomerId == customer_id)
            )
            user = result.scalar_one_or_none()
            if user:
                return user
        user_id = _get(_get(subscription, "metadata"), "user_id")
        return await self.db.get(User, user_id) if user_id else None

    async def handle_event(self, event: Any) -> None:
        """Keeps the user's plan in step with Stripe. Events can arrive late
        or out of order, so the subscription is read fresh from Stripe and
        that state is applied."""
        event_type = _get(event, "type") or ""
        obj = _get(_get(event, "data"), "object")

        if event_type.startswith("customer.subscription."):
            subscription_id = _get(obj, "id")
        elif event_type in (
            "invoice.paid",
            "invoice.payment_succeeded",
            "invoice.payment_failed",
        ):
            subscription_id = invoice_subscription_id(obj)
        else:
            return
        if not subscription_id:
            return

        subscription = await self._retrieve_subscription(subscription_id)
        if subscription is None:
            if not event_type.startswith("customer.subscription."):
                return
            subscription = obj  # deleted for good: the event has its last state

        user = await self._user_for(subscription)
        if user is None:
            logger.warning(
                "Stripe event %s: no user for %s", event_type, subscription_id
            )
            return
        await self.sync_subscription(user, subscription)
