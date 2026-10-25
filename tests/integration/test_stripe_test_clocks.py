"""Payments made days ago, on Stripe's sandbox, with test clocks: each test
starts a clock N days in the past, pays the Pro checkout there with Stripe's
test cards, then moves the clock to today (or past the paid month), so the
charges really are from N days ago — in Stripe and in the Dashboard.

What depends on time: the paid month, cancelling at its end, the renewal
(and a card that fails it), and which subscription stays when there are two.

Only in test mode and only when asked (the clocks are deleted at the end,
with their customers; set KEEP_STRIPE_CLOCKS=1 to look at them in the
Dashboard → Billing → Test clocks):
    RUN_STRIPE_SANDBOX=1 .venv/bin/python -m pytest tests/integration/test_stripe_test_clocks.py
https://docs.stripe.com/billing/testing/test-clocks
"""

import asyncio
import os
import time
import uuid
from collections import defaultdict
from types import SimpleNamespace

import pytest
import stripe
from fastapi import HTTPException

from app.config import settings
from app.modules.billing.services import stripe_service as service_module
from app.modules.billing.services.stripe_service import (
    StripeService,
    subscription_period_end,
)
from tests.integration.test_stripe_sandbox import (
    checkout,
    net_charged,
    pay,
    subscriptions,
    sync,
    wait_for,
)
from tests.stripe_fake import FakeDatabase

DAY = 24 * 60 * 60

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("RUN_STRIPE_SANDBOX") != "1",
        reason="uses Stripe: set RUN_STRIPE_SANDBOX=1",
    ),
    pytest.mark.skipif(
        not settings.STRIPE_SECRET_KEY.startswith("sk_test_"),
        reason="only ever with a test-mode key",
    ),
    pytest.mark.skipif(not settings.STRIPE_PRICE_ID_PRO, reason="no Pro price"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def price() -> int:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe.Price.retrieve(settings.STRIPE_PRICE_ID_PRO).unit_amount


@pytest.fixture
def started_days_ago(monkeypatch):
    """A user whose Stripe customer lives on a test clock set N days back."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    monkeypatch.setattr(service_module, "_checkout_locks", defaultdict(asyncio.Lock))
    # Paid at once unless a test turns the free trial on.
    monkeypatch.setattr(service_module.settings, "PRO_TRIAL_DAYS", 0)
    clocks: list[str] = []

    def make(days_ago: float) -> SimpleNamespace:
        start = int(time.time() - days_ago * DAY)
        clock = stripe.test_helpers.TestClock.create(
            frozen_time=start, name=f"Focusly tests: paid {days_ago:g} days ago"
        )
        clocks.append(clock.id)
        database = FakeDatabase()
        user_id = f"clock-{uuid.uuid4()}"
        email = f"focusly-clock+{uuid.uuid4().hex[:10]}@example.com"
        database.add_user(id=user_id, email=email)
        customer = stripe.Customer.create(
            email=email,
            name=f"Focusly clock test ({days_ago:g} days ago)",
            metadata={"user_id": user_id},
            test_clock=clock.id,
        )
        database.rows[user_id]["stripeCustomerId"] = customer.id
        return SimpleNamespace(
            database=database,
            user_id=user_id,
            clock=clock.id,
            start=start,
            customer=customer.id,
        )

    yield make
    if os.environ.get("KEEP_STRIPE_CLOCKS") != "1":
        for clock_id in clocks:
            # Deletes the clock's customers and their subscriptions too.
            stripe.test_helpers.TestClock.delete(clock_id)


def advance(clock_id: str, to: float, timeout: float = 240) -> None:
    """Moves the clock and waits while Stripe bills everything in between."""
    stripe.test_helpers.TestClock.advance(clock_id, frozen_time=int(to))
    deadline = time.time() + timeout
    while True:
        status = stripe.test_helpers.TestClock.retrieve(clock_id).status
        if status == "ready":
            return
        if status == "internal_failure":
            raise AssertionError(f"Stripe could not advance test clock {clock_id}")
        if time.time() > deadline:
            raise AssertionError(f"Test clock {clock_id} still {status}")
        time.sleep(2)


async def pay_pro(account: SimpleNamespace, card: str = "pm_card_visa") -> str:
    """The checkout, paid with `card` at the clock's time."""
    result = await checkout(account.database, account.user_id)
    assert pay(result["client_secret"], card).status == "succeeded"
    assert wait_for(result["subscription_id"], {"active"}) == "active"
    await sync(account.database, account.user_id)
    return result["subscription_id"]


def charges(customer: str) -> list:
    data = stripe.Charge.list(customer=customer, limit=100).data
    return sorted((c for c in data if c.status == "succeeded"), key=lambda c: c.created)


async def status(account: SimpleNamespace) -> dict:
    session = account.database.session()
    user = await session.get(None, account.user_id)
    return await StripeService(session).get_status(user, refresh=True)


def row(account: SimpleNamespace) -> dict:
    return account.database.rows[account.user_id]


class TestPaidDaysAgo:
    @pytest.mark.parametrize("days_ago", [2, 3, 7, 15])
    async def test_still_pro_until_the_month_ends(
        self, started_days_ago, price, days_ago
    ):
        account = started_days_ago(days_ago)
        sub_id = await pay_pro(account)
        advance(account.clock, time.time())

        # Paid N days ago: the subscription, its month and the invoice are
        # dated on the clock. (Only the Charge object carries the real time:
        # Stripe stamps a payment confirmed from the browser when it happens.)
        sub = stripe.Subscription.retrieve(sub_id, expand=["latest_invoice"])
        invoice = sub.latest_invoice
        assert invoice.status == "paid"
        assert abs(invoice.status_transitions.paid_at - account.start) < 3600
        assert abs(sub["items"]["data"][0].current_period_start - account.start) < 60
        # One payment, nothing renewed yet.
        assert len(charges(account.customer)) == 1
        assert net_charged(account.customer) == price

        info = await status(account)
        assert info["plan"] == "pro"
        assert info["subscription_status"] == "active"
        assert not info["cancel_at_period_end"]
        # The paid month runs from the payment, ~30 days after it.
        period_end = info["current_period_end"]
        assert period_end > time.time()
        assert 27 * DAY <= period_end - account.start <= 32 * DAY
        assert row(account)["stripeSubscriptionId"] == sub_id

        # Paying again days later: refused, no second subscription.
        with pytest.raises(HTTPException) as exc:
            await checkout(account.database, account.user_id)
        assert exc.value.status_code == 409
        assert len(subscriptions(account.customer)) == 1


class TestRenewal:
    async def test_paid_a_month_ago_renews_with_the_same_card(
        self, started_days_ago, price
    ):
        account = started_days_ago(33)
        sub_id = await pay_pro(account)
        first_end = subscription_period_end(stripe.Subscription.retrieve(sub_id))
        advance(account.clock, time.time())

        # Charged again when the month ended (~3 days ago), automatically:
        # a second invoice, paid at the end of the first month.
        invoices = sorted(
            stripe.Invoice.list(subscription=sub_id, limit=10).data,
            key=lambda inv: inv.created,
        )
        assert [inv.status for inv in invoices] == ["paid", "paid"]
        assert abs(invoices[1].status_transitions.paid_at - first_end) < 2 * DAY
        assert first_end < time.time()
        assert len(charges(account.customer)) == 2
        assert net_charged(account.customer) == 2 * price

        await sync(account.database, account.user_id)
        info = await status(account)
        assert info["plan"] == "pro"
        assert info["current_period_end"] > first_end
        assert len(subscriptions(account.customer, "active")) == 1

    async def test_a_renewal_declined_two_days_ago_keeps_pro_while_past_due(
        self, started_days_ago, price
    ):
        account = started_days_ago(32)
        sub_id = await pay_pro(account)
        first_end = subscription_period_end(stripe.Subscription.retrieve(sub_id))

        # The card on file stops working (attaches fine, every charge fails).
        failing = stripe.PaymentMethod.attach(
            "pm_card_chargeCustomerFail", customer=account.customer
        )
        stripe.Subscription.modify(sub_id, default_payment_method=failing.id)
        advance(account.clock, time.time())

        sub = stripe.Subscription.retrieve(sub_id, expand=["latest_invoice"])
        assert sub.status == "past_due"
        assert sub.latest_invoice.status == "open"
        assert sub.latest_invoice.attempt_count >= 1
        assert sub.latest_invoice.created >= first_end - DAY
        # Only the first month was charged.
        assert net_charged(account.customer) == price

        # Stripe keeps retrying: Pro stays meanwhile (past_due gives access).
        await sync(account.database, account.user_id)
        info = await status(account)
        assert info["plan"] == "pro"
        assert info["subscription_status"] == "past_due"
        assert row(account)["subscriptionStatus"] == "pro"


class TestCancellation:
    async def test_cancelled_three_days_after_paying_keeps_pro_until_month_end(
        self, started_days_ago, price
    ):
        account = started_days_ago(3)
        sub_id = await pay_pro(account)
        advance(account.clock, time.time())

        session = account.database.session()
        user = await session.get(None, account.user_id)
        result = await StripeService(session).cancel_subscription(user)
        assert result["cancel_at_period_end"] is True

        # The rest of the paid month is still Pro.
        info = await status(account)
        assert info["plan"] == "pro"
        assert info["cancel_at_period_end"] is True
        period_end = info["current_period_end"]

        # A day after the month ends: over, Free, and no renewal charge.
        advance(account.clock, period_end + DAY)
        assert wait_for(sub_id, {"canceled"}) == "canceled"
        await sync(account.database, account.user_id)
        assert row(account)["subscriptionStatus"] == "free"
        assert row(account)["stripeSubscriptionId"] is None
        assert len(charges(account.customer)) == 1
        assert net_charged(account.customer) == price

        # Coming back later is a new checkout, charged once.
        await pay_pro(account)
        assert row(account)["subscriptionStatus"] == "pro"
        assert net_charged(account.customer) == 2 * price


class TestDuplicateDaysLater:
    async def test_a_second_subscription_three_days_later_is_refunded(
        self, started_days_ago, price
    ):
        account = started_days_ago(3)
        first = await pay_pro(account)
        advance(account.clock, time.time())

        # A second paid subscription appears today (another path, a retried
        # request…): created and charged straight on Stripe.
        card = stripe.PaymentMethod.attach("pm_card_visa", customer=account.customer)
        second = stripe.Subscription.create(
            customer=account.customer,
            items=[{"price": settings.STRIPE_PRICE_ID_PRO}],
            default_payment_method=card.id,
            metadata={"user_id": account.user_id},
        )
        assert wait_for(second.id, {"active"}) == "active"
        assert net_charged(account.customer) == 2 * price

        # Its webhook arrives: the older one (paid 3 days ago) stays, the
        # new one is cancelled and its charge refunded.
        await StripeService(account.database.session()).handle_event(
            {
                "type": "customer.subscription.created",
                "data": {"object": {"id": second.id}},
            }
        )

        assert row(account)["stripeSubscriptionId"] == first
        assert row(account)["subscriptionStatus"] == "pro"
        assert stripe.Subscription.retrieve(second.id).status == "canceled"
        assert stripe.Subscription.retrieve(first).status == "active"
        assert net_charged(account.customer) == price
        refunded = [c for c in charges(account.customer) if c.amount_refunded]
        assert len(refunded) == 1
        assert refunded[0].amount_refunded == price
        # The month paid 3 days ago is untouched.
        kept = stripe.Subscription.retrieve(first, expand=["latest_invoice"])
        assert kept.latest_invoice.status == "paid"
        assert (
            abs(kept.latest_invoice.status_transitions.paid_at - account.start) < 3600
        )
