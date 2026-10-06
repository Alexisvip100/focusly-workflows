from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import stripe
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.database import get_db
from app.modules.ai.routes import ai as ai_routes
from app.modules.billing import routes as billing_routes
from app.modules.billing.plans import FREE_AI_MESSAGE_LIMIT, is_editor_request
from app.modules.billing.services import stripe_service as service_module
from app.modules.billing.services.stripe_service import (
    StripeService,
    invoice_subscription_id,
    subscription_client_secret,
    subscription_period_end,
)
from app.routes.common import get_current_user_id


def make_user(**kwargs):
    defaults = dict(
        id="user-1",
        email="ana@example.com",
        name="Ana",
        subscriptionStatus="free",
        stripeCustomerId="cus_1",
        stripeSubscriptionId=None,
        aiMessagesUsed=0,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_db():
    db = MagicMock()
    db.commit = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    return db


def stripe_obj(data):
    return stripe.StripeObject.construct_from(data, "sk_test")


def subscription(sub_id="sub_1", status="active", **extra):
    return stripe_obj(
        {
            "id": sub_id,
            "status": status,
            "customer": "cus_1",
            "metadata": {"user_id": "user-1"},
            "items": {
                "object": "list",
                "data": [
                    {
                        "current_period_end": 1_800_000_000,
                        "price": {
                            "unit_amount": 999,
                            "currency": "usd",
                            "recurring": {"interval": "month"},
                        },
                    }
                ],
            },
            **extra,
        }
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(service_module.settings, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO", "price_pro")


class TestStripeShapes:
    def test_reads_new_api_invoices_and_old_ones(self):
        invoice = stripe_obj(
            {"parent": {"subscription_details": {"subscription": "sub_9"}}}
        )
        assert invoice_subscription_id(invoice) == "sub_9"
        assert invoice_subscription_id({"subscription": "sub_old"}) == "sub_old"

    def test_period_end_lives_on_the_items(self):
        assert subscription_period_end(subscription()) == 1_800_000_000

    def test_client_secret_of_a_payment_or_a_setup(self):
        paid = subscription(
            status="incomplete",
            latest_invoice={"confirmation_secret": {"client_secret": "pi_s"}},
        )
        assert subscription_client_secret(paid) == ("pi_s", "payment")
        trial = subscription(
            status="trialing", pending_setup_intent={"client_secret": "seti_s"}
        )
        assert subscription_client_secret(trial) == ("seti_s", "setup")


class TestSyncSubscription:
    @pytest.mark.anyio
    async def test_an_active_subscription_makes_the_user_pro(self):
        user = make_user()
        await StripeService(make_db()).sync_subscription(user, subscription())
        assert user.subscriptionStatus == "pro"
        assert user.stripeSubscriptionId == "sub_1"

    @pytest.mark.anyio
    async def test_a_failing_card_keeps_access_while_stripe_retries(self):
        user = make_user(subscriptionStatus="pro", stripeSubscriptionId="sub_1")
        await StripeService(make_db()).sync_subscription(
            user, subscription(status="past_due")
        )
        assert user.subscriptionStatus == "pro"

    @pytest.mark.anyio
    async def test_cancelled_subscription_downgrades(self):
        user = make_user(subscriptionStatus="pro", stripeSubscriptionId="sub_1")
        await StripeService(make_db()).sync_subscription(
            user, subscription(status="canceled")
        )
        assert user.subscriptionStatus == "free"
        assert user.stripeSubscriptionId is None

    @pytest.mark.anyio
    async def test_an_old_abandoned_checkout_cant_downgrade_the_current_plan(self):
        user = make_user(subscriptionStatus="pro", stripeSubscriptionId="sub_new")
        db = make_db()
        await StripeService(db).sync_subscription(
            user, subscription("sub_old", status="incomplete_expired")
        )
        assert user.subscriptionStatus == "pro"
        assert user.stripeSubscriptionId == "sub_new"
        db.commit.assert_not_called()


class TestCreateSubscription:
    @pytest.mark.anyio
    async def test_charges_the_servers_price(self, configured, monkeypatch):
        created = subscription(
            status="incomplete",
            latest_invoice={"confirmation_secret": {"client_secret": "pi_s"}},
        )
        create = MagicMock(return_value=created)
        monkeypatch.setattr(stripe.Subscription, "create", create)
        session = MagicMock(return_value=stripe_obj({"client_secret": "cuss_s"}))
        monkeypatch.setattr(stripe.CustomerSession, "create", session)
        user = make_user()

        result = await StripeService(make_db()).create_subscription(user)

        assert create.call_args.kwargs["items"] == [{"price": "price_pro"}]
        assert "latest_invoice.payment_intent" not in create.call_args.kwargs["expand"]
        assert result["client_secret"] == "pi_s"  # noqa: S105 (test value)
        assert result["intent_type"] == "payment"
        assert result["amount"] == 999
        assert user.stripeSubscriptionId == "sub_1"
        # Saved cards are shown, but can't be removed or re-saved from here.
        assert result["customer_session_client_secret"] == "cuss_s"  # noqa: S105
        features = session.call_args.kwargs["components"]["payment_element"]["features"]
        assert features["payment_method_redisplay"] == "enabled"
        assert features["payment_method_remove"] == "disabled"
        assert features["payment_method_save"] == "disabled"
        assert "unspecified" not in features["payment_method_allow_redisplay_filters"]

    @pytest.mark.anyio
    async def test_checkout_works_without_saved_cards(self, configured, monkeypatch):
        monkeypatch.setattr(
            stripe.Subscription,
            "create",
            MagicMock(
                return_value=subscription(
                    status="incomplete",
                    latest_invoice={"confirmation_secret": {"client_secret": "pi"}},
                )
            ),
        )
        monkeypatch.setattr(
            stripe.CustomerSession,
            "create",
            MagicMock(side_effect=stripe.InvalidRequestError("nope", None)),
        )
        result = await StripeService(make_db()).create_subscription(make_user())
        assert result["client_secret"] == "pi"  # noqa: S105 (test value)
        assert result["customer_session_client_secret"] is None

    @pytest.mark.anyio
    async def test_an_abandoned_checkout_is_cancelled_before_a_new_one(
        self, configured, monkeypatch
    ):
        monkeypatch.setattr(
            stripe.Subscription,
            "retrieve",
            MagicMock(return_value=subscription("sub_old", status="incomplete")),
        )
        cancel = MagicMock()
        monkeypatch.setattr(stripe.Subscription, "cancel", cancel)
        monkeypatch.setattr(
            stripe.Subscription,
            "create",
            MagicMock(
                return_value=subscription(
                    "sub_new",
                    status="incomplete",
                    latest_invoice={"confirmation_secret": {"client_secret": "pi"}},
                )
            ),
        )
        user = make_user(stripeSubscriptionId="sub_old")
        await StripeService(make_db()).create_subscription(user)
        cancel.assert_called_once_with("sub_old")
        assert user.stripeSubscriptionId == "sub_new"

    @pytest.mark.anyio
    async def test_paid_but_webhook_pending_is_not_charged_twice(
        self, configured, monkeypatch
    ):
        monkeypatch.setattr(
            stripe.Subscription, "retrieve", MagicMock(return_value=subscription())
        )
        create = MagicMock()
        monkeypatch.setattr(stripe.Subscription, "create", create)
        user = make_user(stripeSubscriptionId="sub_1")
        with pytest.raises(HTTPException) as exc:
            await StripeService(make_db()).create_subscription(user)
        assert exc.value.status_code == 409
        assert user.subscriptionStatus == "pro"
        create.assert_not_called()

    @pytest.mark.anyio
    async def test_without_a_price_configured_nothing_is_charged(self, monkeypatch):
        monkeypatch.setattr(service_module.settings, "STRIPE_SECRET_KEY", "sk")
        monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO", "")
        with pytest.raises(HTTPException) as exc:
            await StripeService(make_db()).create_subscription(make_user())
        assert exc.value.status_code == 503


class TestStatus:
    @pytest.mark.anyio
    async def test_reports_usage_price_and_a_refreshed_plan(
        self, configured, monkeypatch
    ):
        monkeypatch.setattr(service_module, "_price_cache", {"at": 0.0, "value": None})
        monkeypatch.setattr(
            stripe.Price,
            "retrieve",
            MagicMock(
                return_value=stripe_obj(
                    {
                        "unit_amount": 999,
                        "currency": "usd",
                        "recurring": {"interval": "month"},
                    }
                )
            ),
        )
        monkeypatch.setattr(
            stripe.Subscription,
            "retrieve",
            MagicMock(return_value=subscription(cancel_at_period_end=True)),
        )
        user = make_user(stripeSubscriptionId="sub_1", aiMessagesUsed=2)

        status = await StripeService(make_db()).get_status(user, refresh=True)

        assert status["plan"] == "pro"
        assert status["cancel_at_period_end"] is True
        assert status["current_period_end"] == 1_800_000_000
        assert status["ai_messages_used"] == 2
        assert status["ai_messages_limit"] == FREE_AI_MESSAGE_LIMIT
        assert status["pro_price"] == {
            "amount": 999,
            "currency": "usd",
            "interval": "month",
        }


class TestWebhook:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setattr(billing_routes.settings, "STRIPE_WEBHOOK_SECRET", "whsec")
        self.user = make_user()
        db = make_db()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=self.user)
        db.execute = AsyncMock(return_value=result)
        app = FastAPI()
        app.include_router(billing_routes.router)
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def send(self, client, monkeypatch, event):
        monkeypatch.setattr(
            stripe.Webhook,
            "construct_event",
            MagicMock(return_value=stripe.Event.construct_from(event, "k")),
        )
        return client.post(
            "/api/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=x"},
        )

    def test_a_paid_invoice_makes_the_user_pro(self, client, monkeypatch):
        monkeypatch.setattr(
            stripe.Subscription, "retrieve", MagicMock(return_value=subscription())
        )
        response = self.send(
            client,
            monkeypatch,
            {
                "id": "evt_1",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_1",
                        "parent": {"subscription_details": {"subscription": "sub_1"}},
                    }
                },
            },
        )
        assert response.status_code == 200
        assert self.user.subscriptionStatus == "pro"

    def test_a_deleted_subscription_downgrades(self, client, monkeypatch):
        self.user.subscriptionStatus = "pro"
        self.user.stripeSubscriptionId = "sub_1"
        monkeypatch.setattr(
            stripe.Subscription,
            "retrieve",
            MagicMock(return_value=subscription(status="canceled")),
        )
        response = self.send(
            client,
            monkeypatch,
            {
                "id": "evt_2",
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_1", "customer": "cus_1"}},
            },
        )
        assert response.status_code == 200
        assert self.user.subscriptionStatus == "free"

    def test_unsigned_requests_are_rejected(self, client):
        response = client.post("/api/billing/webhook", content=b"{}")
        assert response.status_code == 400


class TestRegisterDomains:
    def test_registers_the_site_domain_only_once(self, monkeypatch):
        from app.modules.billing import register_domains

        monkeypatch.setattr(register_domains.settings, "STRIPE_SECRET_KEY", "sk")
        monkeypatch.setattr(
            register_domains.settings, "FRONTEND_URL", "https://app.focusly.io"
        )
        existing = stripe_obj({"domain_name": "www.focusly.io"})
        listing = MagicMock()
        listing.auto_paging_iter = MagicMock(return_value=[existing])
        monkeypatch.setattr(
            stripe.PaymentMethodDomain, "list", MagicMock(return_value=listing)
        )
        create = MagicMock(
            return_value=stripe_obj(
                {"domain_name": "app.focusly.io", "apple_pay": {"status": "active"}}
            )
        )
        monkeypatch.setattr(stripe.PaymentMethodDomain, "create", create)

        assert register_domains.main([]) == 0
        create.assert_called_once_with(domain_name="app.focusly.io")

        create.reset_mock()
        assert register_domains.main(["www.focusly.io"]) == 0
        create.assert_not_called()

    def test_skips_localhost(self):
        from app.modules.billing.register_domains import domains_to_register

        assert domains_to_register(["localhost"]) == []


class TestChatLimits:
    def test_tells_editor_requests_from_chat_ones(self):
        assert is_editor_request(
            document_context="doc", persist=True, workspace_id=None
        )
        assert is_editor_request(
            document_context=None, persist=False, workspace_id=None
        )
        assert is_editor_request(document_context=None, persist=True, workspace_id="w1")
        assert not is_editor_request(
            document_context=None, persist=True, workspace_id=None
        )

    @pytest.fixture
    def chat(self, monkeypatch):
        conv_repo = MagicMock()
        conv_repo.create = AsyncMock()
        conv_repo.get_by_id = AsyncMock(return_value=None)
        msg_repo = MagicMock()
        msg_repo.create = AsyncMock()

        async def fake_stream(*args):
            yield "hola"

        monkeypatch.setattr(ai_routes, "ConversationRepository", lambda db: conv_repo)
        monkeypatch.setattr(ai_routes, "MessageRepository", lambda db: msg_repo)
        monkeypatch.setattr(ai_routes, "build_context", AsyncMock(return_value="ctx"))
        monkeypatch.setattr(
            ai_routes, "classify_query", AsyncMock(return_value="simple")
        )
        monkeypatch.setattr(ai_routes, "stream_gemini_and_save", fake_stream)
        state = SimpleNamespace(
            user=make_user(),
            consume=AsyncMock(return_value=3),
            refund=AsyncMock(),
        )
        monkeypatch.setattr(ai_routes, "consume_ai_message", state.consume)
        monkeypatch.setattr(ai_routes, "refund_ai_message", state.refund)

        app = FastAPI()
        app.include_router(ai_routes.router)
        db = make_db()
        db.get = AsyncMock(side_effect=lambda model, id: state.user)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user_id] = lambda: "user-1"
        return TestClient(app), state

    MESSAGES = [{"role": "user", "content": "Hola"}]

    def test_free_chat_message_is_counted_and_reports_whats_left(self, chat):
        client, state = chat
        response = client.post("/ai/chat", json={"messages": self.MESSAGES})
        assert response.status_code == 200
        state.consume.assert_awaited_once()
        assert response.headers["X-AI-Messages-Remaining"] == str(
            FREE_AI_MESSAGE_LIMIT - 3
        )

    def test_over_the_limit_asks_for_pro(self, chat):
        client, state = chat
        state.consume.return_value = None
        response = client.post("/ai/chat", json={"messages": self.MESSAGES})
        assert response.status_code == 402
        assert response.json()["detail"] == {
            "code": "free_limit_reached",
            "limit": FREE_AI_MESSAGE_LIMIT,
        }

    def test_editor_assistant_is_pro_only(self, chat):
        client, state = chat
        response = client.post(
            "/ai/chat",
            json={"messages": self.MESSAGES, "document_context": "doc"},
        )
        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "pro_required"
        state.consume.assert_not_called()

    def test_pro_users_are_not_counted(self, chat):
        client, state = chat
        state.user.subscriptionStatus = "pro"
        response = client.post("/ai/chat", json={"messages": self.MESSAGES})
        assert response.status_code == 200
        state.consume.assert_not_called()
        assert "X-AI-Messages-Remaining" not in response.headers

    def test_a_rejected_request_gives_the_message_back(self, chat):
        client, state = chat
        response = client.post(
            "/ai/chat",
            json={"messages": self.MESSAGES, "conversationId": "missing"},
        )
        assert response.status_code == 404
        state.refund.assert_awaited_once()
