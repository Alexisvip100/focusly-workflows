"""A user is never charged twice for Pro: not with double clicks, two tabs,
retried requests, a payment that failed and was retried, a price change, a
webhook that arrives late, twice or out of order, nor if a race ever slips
through (the duplicate is cancelled and refunded).

Runs against tests/stripe_fake.py: an in-memory Stripe with Stripe's own
rules (one charge per PaymentIntent, cancelling voids the unpaid invoice,
idempotency keys replay) and slow calls, so races really happen."""

import asyncio
from collections import defaultdict

import httpx
import pytest
import stripe
from fastapi import FastAPI, HTTPException

from app.database import get_db
from app.modules.billing import routes as billing_routes
from app.modules.billing.services import stripe_service as service_module
from app.modules.billing.services.stripe_service import StripeService
from app.routes.common import get_current_user_id
from tests.stripe_fake import AMOUNT, PRICE_OLD, PRICE_PRO, FakeDatabase, FakeStripe

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake(monkeypatch) -> FakeStripe:
    monkeypatch.setattr(service_module.settings, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO", PRICE_PRO)
    # Fresh per-user locks (they belong to one event loop).
    monkeypatch.setattr(service_module, "_checkout_locks", defaultdict(asyncio.Lock))
    return FakeStripe().install(monkeypatch)


@pytest.fixture
def database() -> FakeDatabase:
    database = FakeDatabase()
    database.add_user(id="user-1")
    database.add_user(id="user-2", email="luis@example.com")
    return database


async def checkout(database: FakeDatabase, user_id: str = "user-1") -> dict:
    """One POST /subscribe: its own session, its own copy of the user."""
    session = database.session()
    user = await session.get(None, user_id)
    return await StripeService(session).create_subscription(user)


async def webhook(database: FakeDatabase, fake: FakeStripe, sub_id: str) -> None:
    """customer.subscription.updated for sub_id, as Stripe sends it."""
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"id": sub_id}},
    }
    await StripeService(database.session()).handle_event(event)


def customer_of(database: FakeDatabase, user_id: str = "user-1") -> str:
    return database.rows[user_id]["stripeCustomerId"]


# ─── Clicks, tabs, retries ─────────────────────────────────────────────────────


class TestOnePaymentPerCheckout:
    async def test_twenty_simultaneous_clicks_make_one_subscription(
        self, fake, database
    ):
        results = await asyncio.gather(*(checkout(database) for _ in range(20)))

        assert fake.calls["Subscription.create"] == 1
        assert fake.calls["Customer.create"] == 1
        assert {r["subscription_id"] for r in results} == {
            database.rows["user-1"]["stripeSubscriptionId"]
        }
        # Every tab got the same payment: Stripe charges it at most once.
        assert len({r["client_secret"] for r in results}) == 1

    async def test_paying_from_every_tab_charges_once(self, fake, database):
        results = await asyncio.gather(*(checkout(database) for _ in range(5)))
        fake.pay(results[0]["client_secret"])
        for other in results[1:]:
            with pytest.raises(stripe.InvalidRequestError):
                fake.pay(other["client_secret"])

        assert fake.charged() == AMOUNT
        assert fake.paying(customer_of(database)) == [results[0]["subscription_id"]]

    async def test_clicks_one_after_another_reuse_the_checkout(self, fake, database):
        first = await checkout(database)
        for _ in range(5):
            again = await checkout(database)
            assert again["client_secret"] == first["client_secret"]
        assert fake.calls["Subscription.create"] == 1
        assert fake.calls["Subscription.cancel"] == 0

    async def test_two_users_at_once_each_get_their_own(self, fake, database):
        one, two = await asyncio.gather(
            checkout(database, "user-1"), checkout(database, "user-2")
        )
        assert one["subscription_id"] != two["subscription_id"]
        assert customer_of(database, "user-1") != customer_of(database, "user-2")
        assert fake.calls["Subscription.create"] == 2

    async def test_without_the_lock_the_race_is_real(self, fake, database, monkeypatch):
        """Control: proves the tests above can fail. With no per-user lock
        (and no row lock, as here), simultaneous clicks create several
        subscriptions, each payable on its own: a double charge."""

        class NoLock:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(
            service_module, "_checkout_locks", defaultdict(lambda: NoLock())
        )
        results = await asyncio.gather(*(checkout(database) for _ in range(10)))
        assert fake.calls["Subscription.create"] > 1
        secrets = {r["client_secret"] for r in results}
        for secret in secrets:
            fake.pay(secret)
        assert fake.charged() > AMOUNT


class TestFailedPayments:
    async def test_a_declined_card_then_a_good_one_charges_once(self, fake, database):
        first = await checkout(database)
        with pytest.raises(stripe.CardError):
            fake.pay(first["client_secret"], decline="card_declined")

        retry = await checkout(database)
        assert retry["client_secret"] == first["client_secret"]
        fake.pay(retry["client_secret"])

        assert fake.calls["Subscription.create"] == 1
        assert fake.charged() == AMOUNT

    @pytest.mark.parametrize(
        "decline",
        [
            "card_declined",
            "insufficient_funds",
            "expired_card",
            "incorrect_cvc",
            "processing_error",
            "lost_card",
            "stolen_card",
        ],
    )
    async def test_declines_never_make_the_user_pro(self, fake, database, decline):
        result = await checkout(database)
        with pytest.raises(stripe.CardError):
            fake.pay(result["client_secret"], decline=decline)
        await webhook(database, fake, result["subscription_id"])

        assert database.rows["user-1"]["subscriptionStatus"] == "free"
        assert fake.charged() == 0

    async def test_stripe_failing_mid_checkout_keeps_the_customer(
        self, fake, database, monkeypatch
    ):
        create = stripe.Subscription.create

        def broken(**_):
            raise stripe.APIConnectionError("network down")

        monkeypatch.setattr(stripe.Subscription, "create", broken)
        with pytest.raises(HTTPException) as exc:
            await checkout(database)
        assert exc.value.status_code == 502
        customer = customer_of(database)
        assert customer is not None
        assert database.rows["user-1"]["stripeSubscriptionId"] is None

        monkeypatch.setattr(stripe.Subscription, "create", create)
        result = await checkout(database)
        assert customer_of(database) == customer
        fake.pay(result["client_secret"])
        assert fake.charged() == AMOUNT


class TestAbandonedCheckouts:
    async def test_a_checkout_for_an_old_price_is_cancelled_and_unpayable(
        self, fake, database, monkeypatch
    ):
        monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO", PRICE_OLD)
        old = await checkout(database)
        monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO", PRICE_PRO)

        new = await checkout(database)

        assert new["subscription_id"] != old["subscription_id"]
        assert fake.subscriptions[old["subscription_id"]]["status"] == "canceled"
        # The old tab can't pay the cancelled checkout any more.
        with pytest.raises(stripe.InvalidRequestError):
            fake.pay(old["client_secret"])
        fake.pay(new["client_secret"])
        assert fake.charged() == AMOUNT
        assert fake.subscriptions[new["subscription_id"]]["price"] == PRICE_PRO

    async def test_a_checkout_deleted_in_stripe_starts_a_new_one(self, fake, database):
        first = await checkout(database)
        del fake.subscriptions[first["subscription_id"]]
        second = await checkout(database)
        assert second["subscription_id"] != first["subscription_id"]


class TestAlreadyPaid:
    async def test_paid_but_webhook_late_is_not_charged_again(self, fake, database):
        result = await checkout(database)
        fake.pay(result["client_secret"])

        with pytest.raises(HTTPException) as exc:
            await checkout(database)

        assert exc.value.status_code == 409
        assert database.rows["user-1"]["subscriptionStatus"] == "pro"
        assert fake.calls["Subscription.create"] == 1
        assert fake.charged() == AMOUNT

    async def test_a_pro_user_never_reaches_stripe(self, fake, database):
        database.rows["user-1"]["subscriptionStatus"] = "pro"
        with pytest.raises(HTTPException) as exc:
            await checkout(database)
        assert exc.value.status_code == 409
        assert fake.calls["Subscription.create"] == 0
        assert fake.calls["Customer.create"] == 0

    async def test_many_clicks_right_after_paying_are_all_refused(self, fake, database):
        result = await checkout(database)
        fake.pay(result["client_secret"])
        outcomes = await asyncio.gather(
            *(checkout(database) for _ in range(10)), return_exceptions=True
        )
        assert all(
            isinstance(o, HTTPException) and o.status_code == 409 for o in outcomes
        )
        assert fake.calls["Subscription.create"] == 1


# ─── If a duplicate ever exists anyway ─────────────────────────────────────────


def two_paid_subscriptions(fake: FakeStripe, database: FakeDatabase):
    """A race that slipped past everything: two subscriptions created and
    paid for the same customer."""
    database.rows["user-1"]["stripeCustomerId"] = "cus_x"
    subs = []
    for _ in range(2):
        sub = fake.subscription_create(
            customer="cus_x",
            items=[{"price": PRICE_PRO}],
            metadata={"user_id": "user-1"},
        )
        fake.pay(sub["latest_invoice"]["confirmation_secret"]["client_secret"])
        subs.append(sub["id"])
    assert fake.charged("cus_x") == 2 * AMOUNT
    return subs


class TestDuplicateSafetyNet:
    @pytest.mark.parametrize("order", ["oldest_first", "newest_first"])
    async def test_the_duplicate_is_cancelled_and_refunded(self, fake, database, order):
        oldest, newest = two_paid_subscriptions(fake, database)
        events = [oldest, newest] if order == "oldest_first" else [newest, oldest]
        for sub_id in events:
            await webhook(database, fake, sub_id)

        assert fake.paying("cus_x") == [oldest]
        assert fake.subscriptions[newest]["status"] == "canceled"
        assert fake.charged("cus_x") == AMOUNT
        assert [r["reason"] for r in fake.refunds] == ["duplicate"]
        assert database.rows["user-1"]["stripeSubscriptionId"] == oldest
        assert database.rows["user-1"]["subscriptionStatus"] == "pro"

    async def test_a_retried_webhook_refunds_once(self, fake, database):
        _, newest = two_paid_subscriptions(fake, database)
        for _ in range(4):
            await webhook(database, fake, newest)
        assert len(fake.refunds) == 1
        assert fake.charged("cus_x") == AMOUNT

    async def test_simultaneous_webhooks_refund_once(self, fake, database):
        oldest, newest = two_paid_subscriptions(fake, database)
        await asyncio.gather(
            *(webhook(database, fake, s) for s in [oldest, newest] * 3)
        )
        assert len(fake.refunds) == 1
        assert fake.charged("cus_x") == AMOUNT
        assert fake.paying("cus_x") == [oldest]

    async def test_the_duplicates_own_deletion_doesnt_downgrade(self, fake, database):
        oldest, newest = two_paid_subscriptions(fake, database)
        await webhook(database, fake, newest)
        await StripeService(database.session()).handle_event(
            {
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": newest}},
            }
        )
        assert database.rows["user-1"]["subscriptionStatus"] == "pro"
        assert database.rows["user-1"]["stripeSubscriptionId"] == oldest

    async def test_a_status_refresh_also_cleans_up(self, fake, database):
        oldest, newest = two_paid_subscriptions(fake, database)
        database.rows["user-1"]["stripeSubscriptionId"] = newest
        session = database.session()
        user = await session.get(None, "user-1")
        status = await StripeService(session).get_status(user, refresh=True)
        assert status["plan"] == "pro"
        assert fake.charged("cus_x") == AMOUNT
        assert database.rows["user-1"]["stripeSubscriptionId"] == oldest


# ─── Through the HTTP route, requests in parallel ──────────────────────────────


class TestSubscribeRoute:
    async def test_parallel_requests_get_one_checkout(self, fake, database):
        app = FastAPI()
        app.include_router(billing_routes.router)
        app.dependency_overrides[get_db] = database.session
        app.dependency_overrides[get_current_user_id] = lambda: "user-1"

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            responses = await asyncio.gather(
                *(c.post("/api/billing/subscribe") for _ in range(15))
            )

        assert [r.status_code for r in responses] == [200] * 15
        assert len({r.json()["client_secret"] for r in responses}) == 1
        assert fake.calls["Subscription.create"] == 1

    async def test_the_client_cant_choose_the_price(self, fake, database):
        app = FastAPI()
        app.include_router(billing_routes.router)
        app.dependency_overrides[get_db] = database.session
        app.dependency_overrides[get_current_user_id] = lambda: "user-1"

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            response = await c.post(
                "/api/billing/subscribe",
                json={"price": "price_cheap", "amount": 1, "items": [{"price": "x"}]},
            )
        assert response.status_code == 200
        sub = fake.subscriptions[response.json()["subscription_id"]]
        assert sub["price"] == PRICE_PRO
        assert response.json()["amount"] == AMOUNT
