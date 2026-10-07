"""The Pro checkout against Stripe's test sandbox, with Stripe's test cards:
real customers, subscriptions, PaymentIntents, charges and refunds.

Only in test mode and only when asked (each test creates a customer in the
sandbox and deletes it at the end):
    RUN_STRIPE_SANDBOX=1 .venv/bin/python -m pytest tests/integration/test_stripe_sandbox.py

The database is the in-memory one from tests/stripe_fake.py; everything
Stripe does is real. https://docs.stripe.com/testing
"""

import asyncio
import os
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import pytest
import stripe
from fastapi import HTTPException

from app.config import settings
from app.modules.billing.services import stripe_service as service_module
from app.modules.billing.services.stripe_service import StripeService
from tests.stripe_fake import FakeDatabase

SANDBOX = os.environ.get("RUN_STRIPE_SANDBOX") == "1"

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not SANDBOX, reason="uses Stripe: set RUN_STRIPE_SANDBOX=1"),
    pytest.mark.skipif(
        not settings.STRIPE_SECRET_KEY.startswith("sk_test_"),
        reason="only ever with a test-mode key",
    ),
    pytest.mark.skipif(not settings.STRIPE_PRICE_ID_PRO, reason="no Pro price"),
]

RETURN_URL = "https://focusly.test/profile/billing"

# Cards that pay. https://docs.stripe.com/testing#cards
GOOD_CARDS = [
    "pm_card_visa",
    "pm_card_visa_debit",
    "pm_card_mastercard",
    "pm_card_mastercard_debit",
    "pm_card_mastercard_prepaid",
    # Cards from other countries.
    "pm_card_br",
    "pm_card_gb",
    pytest.param(
        "pm_card_mx",
        marks=pytest.mark.xfail(
            strict=True,
            raises=stripe.CardError,
            reason=(
                "The Pro price is in USD and Mexican cards are refused for "
                "non-MXN charges ('Non-MXN currencies are not supported for "
                "this card'): an MXN price (or currency_options) is needed."
            ),
        ),
    ),
]

# Brands the account (Mexico) doesn't accept: "Your card is not supported.
# Please use a Visa, MasterCard, or Carnet card".
UNSUPPORTED_CARDS = [
    "pm_card_amex",
    "pm_card_discover",
    "pm_card_diners",
    "pm_card_jcb",
    "pm_card_unionpay",
]

# Cards that are declined, and the code Stripe gives. https://docs.stripe.com/testing#declined-payments
DECLINED_CARDS = [
    ("pm_card_chargeDeclined", "generic_decline"),
    ("pm_card_chargeDeclinedInsufficientFunds", "insufficient_funds"),
    ("pm_card_chargeDeclinedLostCard", "lost_card"),
    ("pm_card_chargeDeclinedStolenCard", "stolen_card"),
    ("pm_card_chargeDeclinedExpiredCard", "expired_card"),
    ("pm_card_chargeDeclinedIncorrectCvc", "incorrect_cvc"),
    ("pm_card_chargeDeclinedProcessingError", "processing_error"),
    ("pm_card_chargeDeclinedFraudulent", "fraudulent"),
    ("pm_card_chargeDeclinedVelocityLimitExceeded", "card_velocity_exceeded"),
    ("pm_card_riskLevelHighest", None),  # blocked by Radar
]

# Cards that need the customer to authenticate (3-D Secure) first.
AUTH_CARDS = ["pm_card_authenticationRequired", "pm_card_threeDSecure2Required"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def price() -> int:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe.Price.retrieve(settings.STRIPE_PRICE_ID_PRO).unit_amount


@pytest.fixture
def account(monkeypatch):
    """A new user (in memory) whose Stripe customer is deleted afterwards."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    monkeypatch.setattr(service_module, "_checkout_locks", defaultdict(asyncio.Lock))
    database = FakeDatabase()
    database.add_user(
        id=f"sandbox-{uuid.uuid4()}",
        email=f"focusly-sandbox+{uuid.uuid4().hex[:10]}@example.com",
    )
    user_id = next(iter(database.rows))
    yield database, user_id
    customer = database.rows[user_id]["stripeCustomerId"]
    if customer:
        # Also cancels the customer's subscriptions.
        stripe.Customer.delete(customer)


async def checkout(database: FakeDatabase, user_id: str) -> dict:
    session = database.session()
    user = await session.get(None, user_id)
    return await StripeService(session).create_subscription(user)


async def sync(database: FakeDatabase, user_id: str) -> None:
    """What the webhook does, for the user's current subscription."""
    sub_id = database.rows[user_id]["stripeSubscriptionId"]
    await StripeService(database.session()).handle_event(
        {"type": "customer.subscription.updated", "data": {"object": {"id": sub_id}}}
    )


def pay(client_secret: str, card: str) -> stripe.PaymentIntent:
    """What the Payment Element does in the browser: confirm with the card."""
    intent_id = client_secret.split("_secret_")[0]
    return stripe.PaymentIntent.confirm(
        intent_id, payment_method=card, return_url=RETURN_URL
    )


def wait_for(sub_id: str, statuses: set[str], timeout: float = 20) -> str:
    deadline = time.time() + timeout
    while True:
        status = stripe.Subscription.retrieve(sub_id).status
        if status in statuses or time.time() > deadline:
            return status
        time.sleep(0.5)


def net_charged(customer: str) -> int:
    """What the customer paid, net of refunds."""
    charges = stripe.Charge.list(customer=customer, limit=100).data
    return sum(c.amount - c.amount_refunded for c in charges if c.status == "succeeded")


def subscriptions(customer: str, status: str = "all") -> list:
    return stripe.Subscription.list(customer=customer, status=status, limit=100).data


class TestCardsThatPay:
    @pytest.mark.parametrize("card", GOOD_CARDS)
    async def test_one_charge_and_pro(self, account, price, card):
        database, user_id = account
        result = await checkout(database, user_id)
        assert result["amount"] == price
        assert result["intent_type"] == "payment"

        intent = pay(result["client_secret"], card)
        assert intent.status == "succeeded"
        assert intent.amount == price
        assert wait_for(result["subscription_id"], {"active"}) == "active"

        await sync(database, user_id)
        assert database.rows[user_id]["subscriptionStatus"] == "pro"
        customer = database.rows[user_id]["stripeCustomerId"]
        assert net_charged(customer) == price
        assert len(subscriptions(customer, "active")) == 1

        # Another click on "Pay" after paying: refused, nothing created.
        with pytest.raises(HTTPException) as exc:
            await checkout(database, user_id)
        assert exc.value.status_code == 409
        assert len(subscriptions(customer)) == 1

    async def test_the_card_stays_for_the_next_months(self, account):
        database, user_id = account
        result = await checkout(database, user_id)
        intent = pay(result["client_secret"], "pm_card_visa")
        wait_for(result["subscription_id"], {"active"})
        sub = stripe.Subscription.retrieve(result["subscription_id"])
        assert sub.default_payment_method == intent.payment_method


class TestCardsTheAccountRefuses:
    @pytest.mark.parametrize("card", UNSUPPORTED_CARDS)
    async def test_refused_without_charge_then_a_visa_charges_once(
        self, account, price, card
    ):
        database, user_id = account
        result = await checkout(database, user_id)
        with pytest.raises(stripe.CardError) as exc:
            pay(result["client_secret"], card)
        assert "not supported" in str(exc.value)

        await sync(database, user_id)
        customer = database.rows[user_id]["stripeCustomerId"]
        assert database.rows[user_id]["subscriptionStatus"] == "free"
        assert net_charged(customer) == 0

        retry = await checkout(database, user_id)
        assert retry["client_secret"] == result["client_secret"]
        pay(retry["client_secret"], "pm_card_visa")
        wait_for(result["subscription_id"], {"active"})
        await sync(database, user_id)
        assert database.rows[user_id]["subscriptionStatus"] == "pro"
        assert net_charged(customer) == price


class TestDeclinedCards:
    @pytest.mark.parametrize("card, code", DECLINED_CARDS)
    async def test_no_charge_no_pro_and_a_retry_charges_once(
        self, account, price, card, code
    ):
        database, user_id = account
        result = await checkout(database, user_id)

        with pytest.raises(stripe.CardError) as exc:
            pay(result["client_secret"], card)
        if code:
            error = exc.value.error
            assert code in {exc.value.code, getattr(error, "decline_code", None)}

        await sync(database, user_id)
        customer = database.rows[user_id]["stripeCustomerId"]
        assert database.rows[user_id]["subscriptionStatus"] == "free"
        assert net_charged(customer) == 0
        assert stripe.Subscription.retrieve(result["subscription_id"]).status == (
            "incomplete"
        )

        # Trying again (new click, maybe another tab) pays the same checkout.
        retry = await checkout(database, user_id)
        assert retry["subscription_id"] == result["subscription_id"]
        assert retry["client_secret"] == result["client_secret"]
        assert pay(retry["client_secret"], "pm_card_visa").status == "succeeded"
        wait_for(result["subscription_id"], {"active"})
        await sync(database, user_id)

        assert database.rows[user_id]["subscriptionStatus"] == "pro"
        assert net_charged(customer) == price
        assert len(subscriptions(customer)) == 1


class TestAuthentication:
    @pytest.mark.parametrize("card", AUTH_CARDS)
    async def test_waits_for_3d_secure_without_charging(self, account, card):
        database, user_id = account
        result = await checkout(database, user_id)

        intent = pay(result["client_secret"], card)
        assert intent.status == "requires_action"

        await sync(database, user_id)
        customer = database.rows[user_id]["stripeCustomerId"]
        assert database.rows[user_id]["subscriptionStatus"] == "free"
        assert net_charged(customer) == 0

        # Abandoned at the 3-D Secure step: coming back reuses the checkout.
        retry = await checkout(database, user_id)
        assert retry["client_secret"] == result["client_secret"]
        assert len(subscriptions(customer)) == 1


class TestNeverTwice:
    async def test_simultaneous_clicks_make_one_checkout(self, account, price):
        database, user_id = account
        results = await asyncio.gather(*(checkout(database, user_id) for _ in range(8)))
        customer = database.rows[user_id]["stripeCustomerId"]

        assert len({r["client_secret"] for r in results}) == 1
        assert len(subscriptions(customer)) == 1
        assert (
            len(stripe.Customer.list(email=database.rows[user_id]["email"]).data) == 1
        )

        pay(results[0]["client_secret"], "pm_card_visa")
        assert net_charged(customer) == price

    async def test_the_same_payment_confirmed_many_times_charges_once(
        self, account, price
    ):
        database, user_id = account
        result = await checkout(database, user_id)

        def attempt(_):
            try:
                return pay(result["client_secret"], "pm_card_visa").status
            except stripe.StripeError as e:
                return type(e).__name__

        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(attempt, range(6)))

        assert outcomes.count("succeeded") >= 1
        customer = database.rows[user_id]["stripeCustomerId"]
        assert net_charged(customer) == price
        assert (
            len([c for c in stripe.Charge.list(customer=customer).data if c.paid]) == 1
        )

    async def test_a_duplicate_that_slipped_through_is_cancelled_and_refunded(
        self, account, price
    ):
        """Two subscriptions paid for one customer, made straight in Stripe
        (bypassing the checkout): the webhook keeps the oldest and refunds
        the other, whichever event arrives first."""
        database, user_id = account
        first = await checkout(database, user_id)
        pay(first["client_secret"], "pm_card_visa")
        customer = database.rows[user_id]["stripeCustomerId"]

        second = stripe.Subscription.create(
            customer=customer,
            items=[{"price": settings.STRIPE_PRICE_ID_PRO}],
            payment_behavior="default_incomplete",
            expand=["latest_invoice.confirmation_secret"],
            metadata={"user_id": user_id},
        )
        pay(second.latest_invoice.confirmation_secret.client_secret, "pm_card_visa")
        wait_for(second.id, {"active"})
        assert net_charged(customer) == 2 * price

        for sub_id in (second.id, first["subscription_id"], second.id):
            await StripeService(database.session()).handle_event(
                {
                    "type": "customer.subscription.updated",
                    "data": {"object": {"id": sub_id}},
                }
            )

        active = subscriptions(customer, "active")
        assert [s.id for s in active] == [first["subscription_id"]]
        assert stripe.Subscription.retrieve(second.id).status == "canceled"
        assert net_charged(customer) == price
        refunds = [
            r
            for c in stripe.Charge.list(customer=customer).data
            for r in stripe.Refund.list(charge=c.id).data
        ]
        assert [r.reason for r in refunds] == ["duplicate"]
        assert (
            database.rows[user_id]["stripeSubscriptionId"] == first["subscription_id"]
        )
        assert database.rows[user_id]["subscriptionStatus"] == "pro"
