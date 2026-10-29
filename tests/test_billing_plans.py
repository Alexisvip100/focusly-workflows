"""Monthly or yearly Pro, promotion codes, the 7-day free trial and the
payment history, on the in-memory Stripe (tests/stripe_fake.py).

The trial matters for double charges too: it starts ("trialing") before the
card is entered, so it must not count as Pro, nor as a paid subscription when
looking for duplicates, until the card is on file."""

import asyncio
from collections import defaultdict
from unittest.mock import MagicMock

import pytest
import stripe
from fastapi import HTTPException

from app.modules.billing.services import stripe_service as service_module
from app.modules.billing.services.stripe_service import StripeService
from tests.stripe_fake import (
    AMOUNT,
    PRICE_PRO,
    PRICE_YEARLY,
    YEARLY_AMOUNT,
    FakeDatabase,
    FakeStripe,
    MemoryCache,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def memory_cache(monkeypatch) -> MemoryCache:
    store = MemoryCache()
    monkeypatch.setattr(service_module, "cache", store)
    return store


@pytest.fixture
def fake(monkeypatch, memory_cache) -> FakeStripe:
    monkeypatch.setattr(service_module.settings, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO", PRICE_PRO)
    monkeypatch.setattr(
        service_module.settings, "STRIPE_PRICE_ID_PRO_YEARLY", PRICE_YEARLY
    )
    monkeypatch.setattr(service_module.settings, "PRO_TRIAL_DAYS", 0)
    monkeypatch.setattr(service_module, "_checkout_locks", defaultdict(asyncio.Lock))
    return FakeStripe().install(monkeypatch)


@pytest.fixture
def with_trial(monkeypatch, fake) -> FakeStripe:
    monkeypatch.setattr(service_module.settings, "PRO_TRIAL_DAYS", 7)
    return fake


@pytest.fixture
def database() -> FakeDatabase:
    database = FakeDatabase()
    database.add_user(id="user-1")
    return database


async def checkout(database, interval="month", code=None, user_id="user-1"):
    session = database.session()
    user = await session.get(None, user_id)
    return await StripeService(session).create_subscription(
        user, interval=interval, promotion_code=code
    )


async def refresh(database, user_id="user-1") -> dict:
    session = database.session()
    user = await session.get(None, user_id)
    return await StripeService(session).get_status(user, refresh=True)


def row(database, user_id="user-1") -> dict:
    return database.rows[user_id]


class TestMonthlyOrYearly:
    async def test_monthly_by_default(self, fake, database):
        result = await checkout(database)
        sub = fake.subscriptions[result["subscription_id"]]
        assert sub["price"] == PRICE_PRO
        assert sub["metadata"]["plan"] == "pro_monthly"
        assert result["interval"] == "month"
        assert result["amount_due"] == AMOUNT

    async def test_yearly_charges_the_yearly_price(self, fake, database):
        result = await checkout(database, "year")
        sub = fake.subscriptions[result["subscription_id"]]
        assert sub["price"] == PRICE_YEARLY
        assert sub["metadata"]["plan"] == "pro_yearly"
        assert result["interval"] == "year"
        assert result["amount_due"] == YEARLY_AMOUNT

    async def test_without_a_yearly_price_there_is_no_yearly_plan(
        self, fake, database, monkeypatch
    ):
        monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO_YEARLY", "")
        with pytest.raises(HTTPException) as exc:
            await checkout(database, "year")
        assert exc.value.status_code == 400
        assert fake.subscriptions == {}

    async def test_switching_plan_cancels_the_open_checkout(self, fake, database):
        monthly = await checkout(database)
        yearly = await checkout(database, "year")
        assert yearly["subscription_id"] != monthly["subscription_id"]
        assert fake.subscriptions[monthly["subscription_id"]]["status"] == "canceled"
        # The monthly payment can no longer be made on top of the yearly one.
        with pytest.raises(stripe.InvalidRequestError):
            fake.pay(monthly["client_secret"])
        fake.pay(yearly["client_secret"])
        assert fake.charged() == YEARLY_AMOUNT

    async def test_the_status_lists_both_prices(self, fake, database, monkeypatch):
        monkeypatch.setattr(service_module, "_price_cache", {})
        prices = {
            PRICE_PRO: (AMOUNT, "month"),
            PRICE_YEARLY: (YEARLY_AMOUNT, "year"),
        }
        monkeypatch.setattr(
            stripe.Price,
            "retrieve",
            lambda pid: stripe.StripeObject.construct_from(
                {
                    "unit_amount": prices[pid][0],
                    "currency": "usd",
                    "recurring": {"interval": prices[pid][1]},
                },
                "sk",
            ),
        )
        status = await refresh(database)
        assert [(p["amount"], p["interval"]) for p in status["pro_prices"]] == [
            (AMOUNT, "month"),
            (YEARLY_AMOUNT, "year"),
        ]


class TestPromotionCodes:
    async def test_a_code_takes_its_discount_off_the_first_payment(
        self, fake, database
    ):
        result = await checkout(database, code="bienvenida20")  # any case
        assert fake.subscriptions[result["subscription_id"]]["promotion_code"] == (
            "BIENVENIDA20"
        )
        assert result["amount_due"] == AMOUNT * 80 // 100
        assert result["discount"] == {
            "code": "BIENVENIDA20",
            "percent_off": 20,
            "amount_off": None,
            "currency": None,
            "duration": "repeating",
            "duration_in_months": 3,
            "end": None,
        }

    @pytest.mark.parametrize("code", ["NOEXISTE", "   ", "X" * 65])
    async def test_an_unknown_code_creates_nothing(self, fake, database, code):
        with pytest.raises(HTTPException) as exc:
            await checkout(database, code=code)
        assert exc.value.status_code == 400
        assert fake.subscriptions == {}

    async def test_a_code_stripe_refuses_for_this_customer(
        self, fake, database, monkeypatch
    ):
        monkeypatch.setattr(
            stripe.Subscription,
            "create",
            MagicMock(side_effect=stripe.InvalidRequestError("first time only", None)),
        )
        with pytest.raises(HTTPException) as exc:
            await checkout(database, code="LANZAMIENTO50")
        assert exc.value.status_code == 400
        assert "no se puede usar" in exc.value.detail

    async def test_applying_a_code_replaces_the_checkout_and_charges_once(
        self, fake, database
    ):
        plain = await checkout(database)
        discounted = await checkout(database, code="LANZAMIENTO50")
        again = await checkout(database, code="LANZAMIENTO50")  # another click
        assert again["subscription_id"] == discounted["subscription_id"]
        assert fake.subscriptions[plain["subscription_id"]]["status"] == "canceled"

        fake.pay(discounted["client_secret"])
        with pytest.raises(stripe.InvalidRequestError):
            fake.pay(plain["client_secret"])
        assert fake.charged() == AMOUNT // 2


class TestFreeTrial:
    async def test_a_new_user_starts_with_a_card_and_pays_nothing_today(
        self, with_trial, database
    ):
        result = await checkout(database)
        assert result["intent_type"] == "setup"
        assert result["amount_due"] == 0
        assert result["trial_end"]
        assert with_trial.charged() == 0

    async def test_no_pro_until_the_card_is_confirmed(self, with_trial, database):
        result = await checkout(database)
        status = await refresh(database)
        assert status["plan"] == "free"
        assert row(database)["subscriptionStatus"] == "free"

        with_trial.pay(result["client_secret"])  # the browser confirms the card
        status = await refresh(database)
        assert status["plan"] == "pro"
        assert status["subscription_status"] == "trialing"
        assert status["trial_end"] == result["trial_end"]
        # The card is now the subscription's: Stripe charges it at trial end.
        sub = with_trial.subscriptions[result["subscription_id"]]
        assert sub["default_payment_method"]

    async def test_twenty_clicks_on_the_trial_make_one_subscription(
        self, with_trial, database
    ):
        results = await asyncio.gather(*(checkout(database) for _ in range(20)))
        assert len({r["subscription_id"] for r in results}) == 1
        assert len(with_trial.subscriptions) == 1

    async def test_after_confirming_the_card_another_click_is_refused(
        self, with_trial, database
    ):
        result = await checkout(database)
        with_trial.pay(result["client_secret"])
        with pytest.raises(HTTPException) as exc:
            await checkout(database)
        assert exc.value.status_code == 409
        assert len(with_trial.subscriptions) == 1

    async def test_one_trial_per_customer(self, with_trial, database):
        result = await checkout(database)
        with_trial.pay(result["client_secret"])
        await refresh(database)
        # The trial ends (cancelled from the portal): coming back pays at once.
        with_trial.subscriptions[result["subscription_id"]]["status"] = "canceled"
        await refresh(database)
        assert row(database)["subscriptionStatus"] == "free"

        status = await refresh(database)
        assert status["trial_days"] == 0
        again = await checkout(database)
        assert again["intent_type"] == "payment"
        assert again["amount_due"] == AMOUNT

    async def test_an_abandoned_trial_checkout_keeps_the_trial(
        self, with_trial, database
    ):
        first = await checkout(database)  # closed without entering a card
        yearly = await checkout(database, "year")  # changes plan instead
        assert with_trial.subscriptions[first["subscription_id"]]["status"] == (
            "canceled"
        )
        assert yearly["intent_type"] == "setup"
        assert (await refresh(database))["trial_days"] == 7

    async def test_a_cardless_trial_is_not_a_paid_duplicate(
        self, with_trial, database, monkeypatch
    ):
        # An older trial checkout left open, then a paid one (e.g. the trial
        # was turned off meanwhile): the paid one is kept, nothing refunded.
        await checkout(database)
        monkeypatch.setattr(service_module.settings, "PRO_TRIAL_DAYS", 0)
        paid = await checkout(database)
        with_trial.pay(paid["client_secret"])
        await refresh(database)
        assert row(database)["stripeSubscriptionId"] == paid["subscription_id"]
        assert with_trial.charged() == AMOUNT
        assert with_trial.refunds == []


class TestPaymentHistory:
    def _invoice(self, **over):
        data = {
            "id": "in_1",
            "number": "F-0001",
            "created": 1_790_000_000,
            "status": "paid",
            "billing_reason": "subscription_create",
            "subtotal": 999,
            "total": 799,
            "amount_paid": 799,
            "currency": "usd",
            "status_transitions": {"paid_at": 1_790_000_100},
            "total_discount_amounts": [{"amount": 200}],
            "lines": {
                "data": [{"period": {"start": 1_790_000_000, "end": 1_792_678_400}}]
            },
            "payments": {"data": [{"payment": {"payment_intent": "pi_1"}}]},
            "hosted_invoice_url": "https://invoice.stripe.com/i/1",
            "invoice_pdf": "https://pay.stripe.com/invoice/1/pdf",
        }
        data.update(over)
        return data

    async def test_lists_what_was_paid_refunded_and_owed(self, fake, monkeypatch):
        invoices = [
            self._invoice(),
            self._invoice(
                id="in_2", payments={"data": [{"payment": {"payment_intent": "pi_2"}}]}
            ),
            self._invoice(
                id="in_3",
                status="open",
                billing_reason="subscription_cycle",
                amount_paid=0,
            ),
            self._invoice(id="in_4", status="open"),  # an unpaid checkout
            self._invoice(id="in_5", status="void"),
            self._invoice(
                id="in_6", subtotal=0, total=0, amount_paid=0, payments={"data": []}
            ),
            self._invoice(
                id="in_7",
                lines={
                    "data": [{"period": {"start": 1_790_000_000, "end": 1_821_536_000}}]
                },
                payments={"data": [{"payment": {"payment_intent": "pi_7"}}]},
            ),
        ]
        listed = MagicMock(
            return_value=stripe.StripeObject.construct_from({"data": invoices}, "sk")
        )
        charges = MagicMock(
            return_value=stripe.StripeObject.construct_from(
                {
                    "data": [
                        {"payment_intent": "pi_1", "amount_refunded": 0},
                        {"payment_intent": "pi_2", "amount_refunded": 799},
                        {"payment_intent": "pi_7", "amount_refunded": 300},
                    ]
                },
                "sk",
            )
        )
        monkeypatch.setattr(stripe.Invoice, "list", listed)
        monkeypatch.setattr(stripe.Charge, "list", charges)
        user = MagicMock(stripeCustomerId="cus_1", id="user-1")

        rows = await StripeService(MagicMock()).list_invoices(user)

        assert [(r["id"], r["status"]) for r in rows] == [
            ("in_1", "paid"),
            ("in_2", "refunded"),
            ("in_3", "open"),  # a renewal the card couldn't pay
            ("in_6", "paid"),
            ("in_7", "partially_refunded"),
        ]
        first = rows[0]
        assert first["discount"] == 200
        assert first["paid_at"] == 1_790_000_100
        assert first["interval"] == "month"
        assert first["invoice_pdf"].endswith("/pdf")
        assert rows[3]["trial"] is True
        assert rows[4]["interval"] == "year"
        assert rows[4]["amount_refunded"] == 300
        assert listed.call_args.kwargs["customer"] == "cus_1"

    async def test_no_customer_no_history(self, fake):
        user = MagicMock(stripeCustomerId=None)
        assert await StripeService(MagicMock()).list_invoices(user) == []


async def test_the_status_tells_the_plans_canvas_limits(fake, database):
    from app.modules.billing.plans import FREE_CANVAS_LIMITS

    status = await refresh(database)
    assert status["canvas_limits"] == FREE_CANVAS_LIMITS.as_dict()
