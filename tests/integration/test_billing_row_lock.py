"""The checkout's row lock, on the real Postgres: two sessions (two
connections, as two server processes would have) starting a checkout for
the same user at once make one subscription. Stripe is the in-memory fake.

Opt-in, it writes a temporary user to the database in DATABASE_URL:
    RUN_DB_TESTS=1 .venv/bin/python -m pytest tests/integration/test_billing_row_lock.py
"""

import asyncio
import os
import uuid
from collections import defaultdict

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.modules.billing.services import stripe_service as service_module
from app.modules.billing.services.stripe_service import StripeService
from app.modules.user.domain.entities.user import User
from tests.stripe_fake import PRICE_PRO, FakeStripe

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("RUN_DB_TESTS") != "1",
        reason="writes to the database: set RUN_DB_TESTS=1",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class NoLock:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
async def sessions(monkeypatch):
    """A session factory on fresh connections, a temporary user, and no
    in-process lock: only the database can keep the checkouts apart."""
    monkeypatch.setattr(service_module.settings, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(service_module.settings, "STRIPE_PRICE_ID_PRO", PRICE_PRO)
    monkeypatch.setattr(service_module, "_checkout_locks", defaultdict(NoLock))

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    user_id = f"billing-lock-test-{uuid.uuid4()}"
    async with factory() as session:
        session.add(User(id=user_id, email=f"{user_id}@example.com", name="Lock"))
        await session.commit()
    try:
        yield factory, user_id
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()


async def checkout(factory, user_id: str) -> dict:
    async with factory() as session:
        user = await session.get(User, user_id)
        return await StripeService(session).create_subscription(user)


async def test_two_processes_one_subscription(sessions, monkeypatch):
    factory, user_id = sessions
    fake = FakeStripe(delay=0.15).install(monkeypatch)

    results = await asyncio.gather(*(checkout(factory, user_id) for _ in range(6)))

    assert fake.calls["Subscription.create"] == 1
    assert len({r["client_secret"] for r in results}) == 1
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.stripeSubscriptionId == results[0]["subscription_id"]


async def test_without_the_row_lock_they_race(sessions, monkeypatch):
    """Control: without SELECT … FOR UPDATE the same checkouts create
    several subscriptions, so the test above really tests the lock."""
    factory, user_id = sessions
    fake = FakeStripe(delay=0.15).install(monkeypatch)

    async def no_row_lock(self, user):
        return user

    monkeypatch.setattr(StripeService, "_lock_user", no_row_lock)
    await asyncio.gather(*(checkout(factory, user_id) for _ in range(6)))
    assert fake.calls["Subscription.create"] > 1
