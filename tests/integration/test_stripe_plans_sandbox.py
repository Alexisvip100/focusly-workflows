"""Yearly Pro, promotion codes, the free trial and the payment history, on
Stripe's sandbox with test cards and test clocks (real subscriptions,
invoices and charges; the clocks are deleted at the end with their
customers unless KEEP_STRIPE_CLOCKS=1).

Needs, in test mode: STRIPE_PRICE_ID_PRO_YEARLY and the promotion codes
BIENVENIDA20 (20% for 3 months) and LANZAMIENTO50 (50% once).
    RUN_STRIPE_SANDBOX=1 .venv/bin/python -m pytest tests/integration/test_stripe_plans_sandbox.py
"""

import time

import pytest
import stripe

from app.config import settings
from app.modules.billing.services import stripe_service as service_module
from app.modules.billing.services.stripe_service import (
    StripeService,
    subscription_period_end,
)
from tests.integration.test_stripe_sandbox import net_charged, pay, wait_for
from tests.integration.test_stripe_test_clocks import (
    DAY,
    advance,
    charges,
    row,
    status,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        __import__("os").environ.get("RUN_STRIPE_SANDBOX") != "1",
        reason="uses Stripe: set RUN_STRIPE_SANDBOX=1",
    ),
    pytest.mark.skipif(
        not settings.STRIPE_SECRET_KEY.startswith("sk_test_"),
        reason="only ever with a test-mode key",
    ),
    pytest.mark.skipif(
        not settings.STRIPE_PRICE_ID_PRO_YEARLY, reason="no yearly Pro price"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def yearly_price() -> int:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe.Price.retrieve(settings.STRIPE_PRICE_ID_PRO_YEARLY).unit_amount


async def start(account, interval="month", code=None) -> dict:
    session = account.database.session()
    user = await session.get(None, account.user_id)
    return await StripeService(session).create_subscription(
        user, interval=interval, promotion_code=code
    )


def confirm_card(client_secret: str, card: str = "pm_card_visa"):
    """What the Payment Element does for a trial: save the card."""
    setup_id = client_secret.split("_secret_")[0]
    return stripe.SetupIntent.confirm(
        setup_id, payment_method=card, return_url="https://focusly.test/billing"
    )


async def history(account) -> list[dict]:
    session = account.database.session()
    user = await session.get(None, account.user_id)
    return await StripeService(session).list_invoices(user)


class TestYearly:
    async def test_paid_a_year_upfront_and_listed_in_the_history(
        self, started_days_ago, yearly_price
    ):
        account = started_days_ago(5)
        result = await start(account, "year")
        assert result["interval"] == "year"
        assert result["amount_due"] == yearly_price
        assert pay(result["client_secret"], "pm_card_visa").status == "succeeded"
        assert wait_for(result["subscription_id"], {"active"}) == "active"
        advance(account.clock, time.time())

        info = await status(account)
        assert info["plan"] == "pro"
        assert info["interval"] == "year"
        # A year from the payment, 5 days ago.
        assert 360 * DAY <= info["current_period_end"] - account.start <= 367 * DAY
        assert net_charged(account.customer) == yearly_price

        rows = await history(account)
        assert len(rows) == 1
        assert rows[0]["status"] == "paid"
        assert rows[0]["interval"] == "year"
        assert rows[0]["amount_paid"] == yearly_price
        assert rows[0]["invoice_pdf"] and rows[0]["hosted_invoice_url"]


class TestPromotionCodes:
    async def test_half_off_once_then_the_full_price(self, started_days_ago, price):
        account = started_days_ago(33)
        result = await start(account, code="lanzamiento50")
        assert result["amount_due"] == price // 2 or result["amount_due"] == round(
            price / 2
        )
        assert result["discount"]["code"] == "LANZAMIENTO50"
        assert result["discount"]["percent_off"] == 50
        pay(result["client_secret"], "pm_card_visa")
        wait_for(result["subscription_id"], {"active"})
        first = result["amount_due"]
        advance(account.clock, time.time())  # the month ended ~3 days ago

        rows = await history(account)
        assert [r["amount_paid"] for r in rows] == [price, first]  # newest first
        assert rows[1]["discount"] == price - first
        assert net_charged(account.customer) == price + first

    async def test_twenty_percent_for_three_months(self, started_days_ago, price):
        account = started_days_ago(2)
        result = await start(account, code="BIENVENIDA20")
        assert result["discount"]["duration"] == "repeating"
        assert result["discount"]["duration_in_months"] == 3
        pay(result["client_secret"], "pm_card_visa")
        wait_for(result["subscription_id"], {"active"})

        info = await status(account)
        assert info["discount"]["percent_off"] == 20
        assert info["discount"]["code"] == "BIENVENIDA20"
        assert info["discount"]["end"] > time.time()
        assert net_charged(account.customer) == result["amount_due"] < price

    async def test_a_made_up_code_charges_nothing(self, started_days_ago):
        from fastapi import HTTPException

        account = started_days_ago(0)
        with pytest.raises(HTTPException) as exc:
            await start(account, code="GRATISPARASIEMPRE")
        assert exc.value.status_code == 400
        assert stripe.Subscription.list(customer=account.customer).data == []


class TestFreeTrial:
    async def test_seven_free_days_then_charged_on_the_card(
        self, started_days_ago, price, monkeypatch
    ):
        monkeypatch.setattr(service_module.settings, "PRO_TRIAL_DAYS", 7)
        account = started_days_ago(9)  # the trial ended 2 days ago
        result = await start(account)
        assert result["intent_type"] == "setup"
        assert result["amount_due"] == 0
        assert abs(result["trial_end"] - (account.start + 7 * DAY)) < 60

        # No card yet: not Pro.
        assert (await status(account))["plan"] == "free"
        assert confirm_card(result["client_secret"]).status == "succeeded"
        info = await status(account)
        assert info["plan"] == "pro"
        assert info["subscription_status"] == "trialing"
        assert net_charged(account.customer) == 0

        advance(account.clock, time.time())
        assert wait_for(result["subscription_id"], {"active"}) == "active"
        assert net_charged(account.customer) == price
        rows = await history(account)
        assert [r["trial"] for r in rows] == [False, True]
        assert rows[0]["amount_paid"] == price

        # Once is enough: no second trial for this customer.
        assert (await status(account))["trial_days"] == 0

    async def test_a_card_that_fails_at_the_end_of_the_trial(
        self, started_days_ago, monkeypatch
    ):
        monkeypatch.setattr(service_module.settings, "PRO_TRIAL_DAYS", 7)
        account = started_days_ago(9)
        result = await start(account)
        confirm_card(result["client_secret"], "pm_card_chargeCustomerFail")
        await status(account)
        advance(account.clock, time.time())

        sub = stripe.Subscription.retrieve(result["subscription_id"])
        assert sub.status == "past_due"
        assert net_charged(account.customer) == 0
        info = await status(account)
        assert info["subscription_status"] == "past_due"
        rows = await history(account)
        assert rows[0]["status"] == "open"  # the renewal the card couldn't pay
        assert subscription_period_end(sub) > time.time()

    async def test_closing_the_trial_form_owes_nothing_and_keeps_the_trial(
        self, started_days_ago, monkeypatch
    ):
        monkeypatch.setattr(service_module.settings, "PRO_TRIAL_DAYS", 7)
        account = started_days_ago(0)
        first = await start(account)
        again = await start(account, "year")  # changes plan without a card
        assert stripe.Subscription.retrieve(first["subscription_id"]).status == (
            "canceled"
        )
        assert again["intent_type"] == "setup"
        assert (await status(account))["trial_days"] == 7
        assert row(account)["subscriptionStatus"] == "free"
        assert len(charges(account.customer)) == 0
