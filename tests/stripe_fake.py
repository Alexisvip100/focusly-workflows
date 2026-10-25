"""An in-memory Stripe for the billing tests: subscriptions, their first
invoice and PaymentIntent, charges and refunds, with Stripe's own rules where
they matter for double charges (an intent is charged once, a cancelled
subscription's invoice can't be paid, idempotency keys replay)."""

import itertools
import threading
import time
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import stripe

PRICE_PRO = "price_pro"
PRICE_YEARLY = "price_pro_yearly"
PRICE_OLD = "price_old"
AMOUNT = 999
YEARLY_AMOUNT = 9990
DAY = 24 * 60 * 60

# Promotion codes the fake knows: code → coupon.
COUPONS = {
    "BIENVENIDA20": {
        "id": "co_20",
        "percent_off": 20,
        "amount_off": None,
        "currency": None,
        "duration": "repeating",
        "duration_in_months": 3,
    },
    "LANZAMIENTO50": {
        "id": "co_50",
        "percent_off": 50,
        "amount_off": None,
        "currency": None,
        "duration": "once",
        "duration_in_months": None,
    },
}


class MemoryCache:
    """app.redis.cache, in memory."""

    def __init__(self):
        self.store: dict[str, Any] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expire_seconds=3600):
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return True


def obj(data: dict[str, Any]) -> stripe.StripeObject:
    return stripe.StripeObject.construct_from(data, "sk_test")


def card_error(code: str) -> stripe.CardError:
    return stripe.CardError(
        "Your card was declined.", None, code=code, json_body={"error": {}}
    )


class FakeStripe:
    def __init__(self, delay: float = 0.02):
        # Each call takes a moment, like the real API: races show up.
        self.delay = delay
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.customers: dict[str, dict] = {}
        self.subscriptions: dict[str, dict] = {}
        self.intents: dict[str, dict] = {}
        self.charges: list[dict] = []
        self.setups: dict[str, dict] = {}
        self.refunds: list[dict] = []
        self._idempotent: dict[str, Any] = {}
        self.calls: defaultdict[str, int] = defaultdict(int)

    def _id(self, prefix: str) -> str:
        return f"{prefix}_{next(self._ids)}"

    def _wait(self, name: str) -> None:
        self.calls[name] += 1
        time.sleep(self.delay)

    def _replay(self, key: str | None, make):
        if key is None:
            return make()
        with self._lock:
            if key not in self._idempotent:
                self._idempotent[key] = make()
            return self._idempotent[key]

    # ── Objects as the SDK returns them ──

    def _subscription_obj(self, sub: dict) -> stripe.StripeObject:
        intent = self.intents.get(sub["intent"]) or {}
        payable = sub["status"] == "incomplete" and intent.get("status") in (
            "requires_payment_method",
            "requires_action",
        )
        setup = self.setups.get(sub.get("setup") or "")
        price_id = sub["price"]
        yearly = price_id == PRICE_YEARLY
        promo = sub.get("promotion_code")
        amount = self._first_payment(sub)
        return obj(
            {
                "id": sub["id"],
                "object": "subscription",
                "status": sub["status"],
                "customer": sub["customer"],
                "created": sub["created"],
                "metadata": sub["metadata"],
                "cancel_at_period_end": False,
                "trial_end": sub.get("trial_end"),
                "default_payment_method": sub.get("default_payment_method"),
                "latest_invoice": {
                    "id": sub["invoice"],
                    "amount_due": 0 if sub.get("trial_end") else amount,
                    "confirmation_secret": {"client_secret": intent["secret"]}
                    if payable
                    else None,
                },
                "pending_setup_intent": {
                    "id": setup["id"],
                    "client_secret": setup["secret"],
                    "status": setup["status"],
                    "payment_method": setup.get("payment_method"),
                }
                if setup
                else None,
                "discounts": [
                    {
                        "promotion_code": f"promo_{promo}",
                        "source": {"coupon": COUPONS[promo]["id"]},
                        "end": None,
                    }
                ]
                if promo
                else [],
                "items": {
                    "object": "list",
                    "data": [
                        {
                            "current_period_end": 1_900_000_000,
                            "price": {
                                "id": price_id,
                                "unit_amount": YEARLY_AMOUNT if yearly else AMOUNT,
                                "currency": "usd",
                                "recurring": {
                                    "interval": "year" if yearly else "month"
                                },
                            },
                        }
                    ],
                },
            }
        )

    @staticmethod
    def _first_payment(sub: dict) -> int:
        """The price of the subscription's plan, less its promotion code."""
        amount = YEARLY_AMOUNT if sub["price"] == PRICE_YEARLY else AMOUNT
        promo = sub.get("promotion_code")
        if promo:
            amount = amount * (100 - COUPONS[promo]["percent_off"]) // 100
        return amount

    # ── stripe.Customer / CustomerSession ──

    def customer_create(self, **kwargs):
        self._wait("Customer.create")

        def make():
            customer_id = self._id("cus")
            self.customers[customer_id] = {"id": customer_id, **kwargs}
            return obj({"id": customer_id})

        return self._replay(kwargs.get("idempotency_key"), make)

    def customer_session_create(self, **kwargs):
        self._wait("CustomerSession.create")
        return obj({"client_secret": f"cuss_{kwargs['customer']}"})

    # ── stripe.Subscription ──

    def subscription_create(self, **kwargs):
        self._wait("Subscription.create")
        trial_days = kwargs.get("trial_period_days")
        discounts = kwargs.get("discounts") or []
        promo = (
            discounts[0]["promotion_code"].removeprefix("promo_") if discounts else None
        )
        with self._lock:
            sub_id = self._id("sub")
            intent_id = self._id("pi")
            setup_id = None
            if trial_days:
                # A trial charges nothing now: the card is set up instead.
                setup_id = self._id("seti")
                self.setups[setup_id] = {
                    "id": setup_id,
                    "secret": f"{setup_id}_secret_x",
                    "status": "requires_payment_method",
                    "subscription": sub_id,
                }
            else:
                self.intents[intent_id] = {
                    "id": intent_id,
                    "secret": f"{intent_id}_secret_x",
                    "status": "requires_payment_method",
                    "subscription": sub_id,
                }
            self.subscriptions[sub_id] = {
                "id": sub_id,
                "status": "trialing" if trial_days else "incomplete",
                "trial_end": int(time.time()) + trial_days * DAY
                if trial_days
                else None,
                "setup": setup_id,
                "promotion_code": promo,
                "default_payment_method": None,
                "customer": kwargs["customer"],
                "price": kwargs["items"][0]["price"],
                "created": next(self._ids),
                "metadata": kwargs.get("metadata", {}),
                "invoice": self._id("in"),
                "intent": intent_id,
                "invoice_status": "open",
            }
        return self._subscription_obj(self.subscriptions[sub_id])

    def subscription_retrieve(self, sub_id, **_):
        self._wait("Subscription.retrieve")
        if sub_id not in self.subscriptions:
            raise stripe.InvalidRequestError(
                "No such subscription", None, code="resource_missing"
            )
        return self._subscription_obj(self.subscriptions[sub_id])

    def subscription_modify(self, sub_id, default_payment_method=None, **_):
        self._wait("Subscription.modify")
        sub = self.subscriptions[sub_id]
        if default_payment_method:
            sub["default_payment_method"] = default_payment_method
        return self._subscription_obj(sub)

    def setup_intent_retrieve(self, setup_id, **_):
        self._wait("SetupIntent.retrieve")
        setup = self.setups[setup_id]
        return obj({**setup, "client_secret": setup["secret"]})

    def promotion_code_list(self, code, **_):
        self._wait("PromotionCode.list")
        coupon = COUPONS.get(code.upper())
        if not coupon:
            return obj({"data": []})
        return obj(
            {
                "data": [
                    {
                        "id": f"promo_{code.upper()}",
                        "code": code.upper(),
                        "promotion": {"type": "coupon", "coupon": coupon},
                    }
                ]
            }
        )

    def promotion_code_retrieve(self, promo_id, **_):
        self._wait("PromotionCode.retrieve")
        return obj({"id": promo_id, "code": promo_id.removeprefix("promo_")})

    def coupon_retrieve(self, coupon_id, **_):
        self._wait("Coupon.retrieve")
        return obj(next(c for c in COUPONS.values() if c["id"] == coupon_id))

    def subscription_cancel(self, sub_id, **_):
        self._wait("Subscription.cancel")
        sub = self.subscriptions[sub_id]
        if sub["status"] == "canceled":
            raise stripe.InvalidRequestError(
                "already canceled", None, code="resource_missing"
            )
        sub["status"] = "canceled"
        if sub["invoice_status"] == "open" and sub["intent"] in self.intents:
            # Cancelling voids the unpaid invoice: its intent can't be paid.
            sub["invoice_status"] = "void"
            self.intents[sub["intent"]]["status"] = "canceled"
        if sub.get("setup") and self.setups[sub["setup"]]["status"] != "succeeded":
            self.setups[sub["setup"]]["status"] = "canceled"
        return self._subscription_obj(sub)

    def subscription_list(self, customer, **_):
        self._wait("Subscription.list")
        return obj(
            {
                "data": [
                    self._subscription_obj(s)
                    for s in self.subscriptions.values()
                    if s["customer"] == customer
                ]
            }
        )

    # ── stripe.Invoice / InvoicePayment / Refund ──

    def invoice_list(self, subscription, status=None, **_):
        self._wait("Invoice.list")
        sub = self.subscriptions[subscription]
        if status and sub["invoice_status"] != status:
            return obj({"data": []})
        return obj({"data": [{"id": sub["invoice"]}]})

    def invoice_payment_list(self, invoice, **_):
        self._wait("InvoicePayment.list")
        sub = next(s for s in self.subscriptions.values() if s["invoice"] == invoice)
        intent = self.intents.get(sub["intent"])
        if not intent or intent["status"] != "succeeded":
            return obj({"data": []})
        return obj(
            {
                "data": [
                    {
                        "payment": {
                            "type": "payment_intent",
                            "payment_intent": intent["id"],
                        }
                    }
                ]
            }
        )

    def refund_create(self, payment_intent, idempotency_key=None, **kwargs):
        self._wait("Refund.create")

        def make():
            charge = next(c for c in self.charges if c["intent"] == payment_intent)
            if charge["refunded"]:
                raise stripe.InvalidRequestError(
                    "already refunded", None, code="charge_already_refunded"
                )
            charge["refunded"] = True
            refund = {"payment_intent": payment_intent, **kwargs}
            self.refunds.append(refund)
            return obj(refund)

        return self._replay(idempotency_key, make)

    # ── What the browser does: confirm the payment with a card ──

    def pay(self, client_secret: str, decline: str | None = None) -> None:
        setup = next(
            (x for x in self.setups.values() if x["secret"] == client_secret), None
        )
        if setup is not None:
            # A trial's card: saved, nothing charged.
            with self._lock:
                if setup["status"] != "requires_payment_method":
                    raise stripe.InvalidRequestError(
                        "This SetupIntent can't be confirmed.",
                        None,
                        code="setup_intent_unexpected_state",
                    )
                if decline:
                    raise card_error(decline)
                setup["status"] = "succeeded"
                setup["payment_method"] = f"pm_{setup['id']}"
            return
        intent = next(i for i in self.intents.values() if i["secret"] == client_secret)
        with self._lock:
            if intent["status"] == "succeeded":
                raise stripe.InvalidRequestError(
                    "This PaymentIntent has already succeeded.",
                    None,
                    code="payment_intent_unexpected_state",
                )
            if intent["status"] == "canceled":
                raise stripe.InvalidRequestError(
                    "This PaymentIntent was canceled.",
                    None,
                    code="payment_intent_unexpected_state",
                )
            if decline:
                intent["status"] = "requires_payment_method"
                raise card_error(decline)
            intent["status"] = "succeeded"
            sub = self.subscriptions[intent["subscription"]]
            sub["status"] = "active"
            sub["invoice_status"] = "paid"
            self.charges.append(
                {
                    "intent": intent["id"],
                    "amount": self._first_payment(sub),
                    "refunded": False,
                }
            )

    # ── Totals the tests check ──

    def charged(self, customer: str | None = None) -> int:
        """What the customer paid, net of refunds."""
        subs = {
            s["intent"]
            for s in self.subscriptions.values()
            if customer is None or s["customer"] == customer
        }
        return sum(
            c["amount"]
            for c in self.charges
            if c["intent"] in subs and not c["refunded"]
        )

    def paying(self, customer: str) -> list[str]:
        return [
            s["id"]
            for s in self.subscriptions.values()
            if s["customer"] == customer and s["status"] in ("active", "trialing")
        ]

    def install(self, monkeypatch) -> "FakeStripe":
        patches = {
            (stripe.Customer, "create"): self.customer_create,
            (stripe.CustomerSession, "create"): self.customer_session_create,
            (stripe.Subscription, "create"): self.subscription_create,
            (stripe.Subscription, "retrieve"): self.subscription_retrieve,
            (stripe.Subscription, "cancel"): self.subscription_cancel,
            (stripe.Subscription, "list"): self.subscription_list,
            (stripe.Subscription, "modify"): self.subscription_modify,
            (stripe.SetupIntent, "retrieve"): self.setup_intent_retrieve,
            (stripe.PromotionCode, "list"): self.promotion_code_list,
            (stripe.PromotionCode, "retrieve"): self.promotion_code_retrieve,
            (stripe.Coupon, "retrieve"): self.coupon_retrieve,
            (stripe.Invoice, "list"): self.invoice_list,
            (stripe.InvoicePayment, "list"): self.invoice_payment_list,
            (stripe.Refund, "create"): self.refund_create,
        }
        for (cls, name), fn in patches.items():
            monkeypatch.setattr(cls, name, fn)
        return self


class FakeDatabase:
    """The users table, shared by every request's session (as in Postgres):
    a session reads its own copy of the row and writes it back on commit."""

    def __init__(self):
        self.rows: dict[str, dict[str, Any]] = {}

    def add_user(self, **fields) -> None:
        row = dict(
            id="user-1",
            email="ana@example.com",
            name="Ana",
            subscriptionStatus="free",
            stripeCustomerId=None,
            stripeSubscriptionId=None,
            aiMessagesUsed=0,
        )
        row.update(fields)
        self.rows[row["id"]] = row

    def session(self) -> "FakeSession":
        return FakeSession(self)


class FakeSession:
    """Like an AsyncSession: an identity map of users, and commits that
    write only the fields this session changed."""

    def __init__(self, database: FakeDatabase):
        self.database = database
        self.loaded: dict[str, SimpleNamespace] = {}
        self._seen: dict[str, dict[str, Any]] = {}
        self.commits = 0

    def _load(self, row: dict[str, Any]) -> SimpleNamespace:
        user = self.loaded.get(row["id"])
        if user is None:
            user = SimpleNamespace(**row)
            self.loaded[row["id"]] = user
        else:
            user.__dict__.update(row)
        self._seen[row["id"]] = dict(row)
        return user

    async def get(self, _model, user_id):
        if user_id in self.loaded:
            return self.loaded[user_id]
        row = self.database.rows.get(user_id)
        return self._load(row) if row else None

    async def execute(self, statement):
        # select(User).where(User.<column> == value): the row as committed now
        # (SELECT … FOR UPDATE with populate_existing refreshes the object).
        column = statement.whereclause.left.name
        value = statement.whereclause.right.value
        row = next(
            (r for r in self.database.rows.values() if r.get(column) == value), None
        )
        user = self._load(row) if row else None
        return SimpleNamespace(scalar_one_or_none=lambda: user)

    async def commit(self):
        self.commits += 1
        for user_id, user in self.loaded.items():
            seen = self._seen[user_id]
            changed = {k: v for k, v in vars(user).items() if seen.get(k) != v}
            self.database.rows[user_id].update(changed)
            self._seen[user_id] = dict(self.database.rows[user_id])

    async def rollback(self):
        for user_id in self.loaded:
            self._load(self.database.rows[user_id])
