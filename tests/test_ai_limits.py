"""How much AI each plan gets: free messages a month, Pro's daily fair use and
monthly cost cap (see billing/plans.py)."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import User
from app.modules.ai.routes import ai as ai_routes
from app.modules.ai.services.focusly_ai import USAGE_MARKER
from app.modules.ai.services.router import LIGHT_MODEL, STRONG_MODEL
from app.modules.billing.plans import (
    FREE_AI_MESSAGE_LIMIT,
    PRO_DAILY_AI_LIMIT,
    PRO_MONTHLY_AI_COST_CAP_USD,
    ai_cost_micros,
)
from app.modules.billing.services import usage_service
from app.modules.billing.services.usage_service import (
    add_ai_cost,
    consume_ai_message,
    consume_daily_ai_use,
    cost_this_month_usd,
    day_resets_at,
    give_back_ai_use,
    messages_used_this_month,
    month_resets_at,
    refund_ai_message,
    take_ai_use,
)
from tests.test_ai_optimization import chat  # noqa: F401 (fixture)

OCT_29 = datetime(2026, 10, 29, 15, tzinfo=timezone.utc)
OCT_30 = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)
NOV_1 = datetime(2026, 11, 1, 0, 5, tzinfo=timezone.utc)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all(
            [
                User(id="free", email="free@test.dev"),
                User(id="pro", email="pro@test.dev", subscriptionStatus="pro"),
            ]
        )
        await s.commit()
        yield s
    await engine.dispose()


async def fresh(session, user_id):
    session.expire_all()
    return await session.get(User, user_id)


# ── Free: messages a month ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_free_messages_run_out_within_the_month(session):
    counts = [await consume_ai_message(session, "free", OCT_29) for _ in range(FREE_AI_MESSAGE_LIMIT)]
    assert counts == list(range(1, FREE_AI_MESSAGE_LIMIT + 1))
    assert await consume_ai_message(session, "free", OCT_30) is None


@pytest.mark.anyio
async def test_free_messages_renew_on_the_first_of_the_month(session):
    for _ in range(FREE_AI_MESSAGE_LIMIT):
        await consume_ai_message(session, "free", OCT_29)
    assert await consume_ai_message(session, "free", NOV_1) == 1
    user = await fresh(session, "free")
    assert messages_used_this_month(user, NOV_1) == 1
    assert messages_used_this_month(user, OCT_29) == 0


@pytest.mark.anyio
async def test_accounts_from_the_lifetime_limit_start_the_month_afresh(session):
    """Before messages were monthly, the count never reset and had no month."""
    user = await fresh(session, "free")
    user.aiMessagesUsed = 5
    await session.commit()
    assert messages_used_this_month(await fresh(session, "free"), OCT_29) == 0
    assert await consume_ai_message(session, "free", OCT_29) == 1


@pytest.mark.anyio
async def test_a_refund_only_gives_back_this_months_message(session):
    await consume_ai_message(session, "free", OCT_29)
    await consume_ai_message(session, "free", OCT_29)
    await refund_ai_message(session, "free", OCT_29)
    assert messages_used_this_month(await fresh(session, "free"), OCT_29) == 1
    # Last month's count isn't touched by a refund in the new one
    await refund_ai_message(session, "free", NOV_1)
    assert messages_used_this_month(await fresh(session, "free"), OCT_29) == 1


def test_the_reset_instants_are_exact_utc_times_the_app_can_localize():
    assert month_resets_at(OCT_29) == "2026-11-01T00:00:00+00:00"
    assert month_resets_at(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)) == (
        "2027-01-01T00:00:00+00:00"
    )
    assert day_resets_at(OCT_29) == "2026-10-30T00:00:00+00:00"
    assert day_resets_at(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)) == (
        "2027-01-01T00:00:00+00:00"
    )


# ── Pro: daily fair use ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_pro_fair_use_is_a_day_and_starts_over_the_next(session):
    for n in range(PRO_DAILY_AI_LIMIT):
        assert await consume_daily_ai_use(session, "pro", OCT_29) == n + 1
    assert await consume_daily_ai_use(session, "pro", OCT_29) is None
    assert await consume_daily_ai_use(session, "pro", OCT_30) == 1


@pytest.mark.anyio
async def test_take_ai_use_counts_each_plan_its_own_way(session):
    free = await take_ai_use(session, "free", await fresh(session, "free"))
    assert (free.pro, free.left) == (False, FREE_AI_MESSAGE_LIMIT - 1)
    assert free.headers() == {"X-AI-Messages-Remaining": str(FREE_AI_MESSAGE_LIMIT - 1)}

    pro = await take_ai_use(session, "pro", await fresh(session, "pro"))
    assert (pro.pro, pro.left, pro.economy) == (True, PRO_DAILY_AI_LIMIT - 1, False)
    assert pro.headers() == {"X-AI-Daily-Remaining": str(PRO_DAILY_AI_LIMIT - 1)}
    # Pro never spends the free messages
    assert messages_used_this_month(await fresh(session, "pro")) == 0


@pytest.mark.anyio
async def test_limits_are_refused_with_codes_the_app_knows(session):
    now = datetime.now(timezone.utc)
    pro = await fresh(session, "pro")
    pro.aiDailyDate, pro.aiDailyUsed = now.strftime("%Y-%m-%d"), PRO_DAILY_AI_LIMIT
    await session.commit()
    free = await fresh(session, "free")
    free.aiPeriod, free.aiMessagesUsed = now.strftime("%Y-%m"), FREE_AI_MESSAGE_LIMIT
    await session.commit()

    with pytest.raises(HTTPException) as daily:
        await take_ai_use(session, "pro", await fresh(session, "pro"))
    assert daily.value.status_code == 429
    assert daily.value.detail == {
        "code": "daily_limit_reached",
        "limit": PRO_DAILY_AI_LIMIT,
        "resets_at": day_resets_at(),
    }

    with pytest.raises(HTTPException) as monthly:
        await take_ai_use(session, "free", await fresh(session, "free"))
    assert monthly.value.status_code == 402
    assert monthly.value.detail == {
        "code": "free_limit_reached",
        "limit": FREE_AI_MESSAGE_LIMIT,
        "resets_at": month_resets_at(),
    }


@pytest.mark.anyio
async def test_a_failed_request_gives_the_use_back(session):
    use = await take_ai_use(session, "pro", await fresh(session, "pro"))
    await give_back_ai_use(session, "pro", use)
    again = await take_ai_use(session, "pro", await fresh(session, "pro"))
    assert again.left == PRO_DAILY_AI_LIMIT - 1


# ── Pro: monthly cost cap ────────────────────────────────────────────────────


def test_a_reply_is_costed_from_its_tokens():
    usage = {"model": "gemini-2.5-flash", "input": 8000, "cached": 6000, "output": 500, "thoughts": 300}
    # 2000 new input × $0.30 + 6000 cached × $0.03 + 800 out × $2.50 (per million)
    assert ai_cost_micros(usage) == 2000 * 0.30 + 6000 * 0.03 + 800 * 2.50
    cheap = {**usage, "model": "gemini-2.5-flash-lite"}
    assert ai_cost_micros(cheap) < ai_cost_micros(usage)


def test_an_unknown_model_is_costed_as_the_dearest():
    usage = {"input": 1000, "output": 1000}
    assert ai_cost_micros({**usage, "model": "gemini-9-ultra"}) == ai_cost_micros(
        {**usage, "model": "gemini-2.5-flash"}
    )
    assert ai_cost_micros(None) == 0


@pytest.mark.anyio
async def test_costs_add_up_through_the_month_and_start_over(session):
    await add_ai_cost(session, "pro", 1_500_000, OCT_29)
    await add_ai_cost(session, "pro", 500_000, OCT_30)
    assert cost_this_month_usd(await fresh(session, "pro"), OCT_30) == 2.0
    await add_ai_cost(session, "pro", 250_000, NOV_1)
    assert cost_this_month_usd(await fresh(session, "pro"), NOV_1) == 0.25


@pytest.mark.anyio
async def test_costs_and_free_messages_share_the_month_without_losing_either(session):
    await consume_ai_message(session, "free", OCT_29)
    await add_ai_cost(session, "free", 10_000, OCT_29)
    await consume_ai_message(session, "free", OCT_29)
    user = await fresh(session, "free")
    assert messages_used_this_month(user, OCT_29) == 2
    assert cost_this_month_usd(user, OCT_29) == 0.01


@pytest.mark.anyio
async def test_past_the_cost_cap_pro_goes_on_the_cheaper_model(session):
    cap = int(PRO_MONTHLY_AI_COST_CAP_USD * 1_000_000)
    await add_ai_cost(session, "pro", cap - 1)
    assert (await take_ai_use(session, "pro", await fresh(session, "pro"))).economy is False
    await add_ai_cost(session, "pro", 1)
    assert (await take_ai_use(session, "pro", await fresh(session, "pro"))).economy is True


# ── In the routes ────────────────────────────────────────────────────────────


def test_past_the_cost_cap_even_planning_uses_the_cheaper_model(chat, monkeypatch):  # noqa: F811
    client, state = chat
    planning = {"messages": [{"role": "user", "content": "Planifica mi semana"}]}

    client.post("/ai/chat", json=planning)
    assert state.streamed["model"] == STRONG_MODEL

    monkeypatch.setattr(usage_service, "cost_this_month_usd", lambda user: PRO_MONTHLY_AI_COST_CAP_USD)
    client.post("/ai/chat", json=planning)
    assert state.streamed["model"] == LIGHT_MODEL


@pytest.mark.anyio
async def test_each_reply_adds_its_cost_to_the_users_month(monkeypatch):
    usage = {"model": "gemini-2.5-flash", "input": 1000, "cached": 0, "output": 100, "thoughts": 0}

    class FakeStream:
        status_code = 200

        async def aiter_text(self):
            yield "Hola"
            yield USAGE_MARKER + json.dumps(usage)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *args, **kwargs):
            outer = FakeStream()

            class Ctx:
                async def __aenter__(self):
                    return outer

                async def __aexit__(self, *exc):
                    return False

            return Ctx()

    recorded = AsyncMock()
    monkeypatch.setattr(ai_routes.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(ai_routes, "add_ai_cost", recorded)

    async def db_factory():
        yield "db"

    await ai_routes.fetch_ai_stream_and_persist(
        "http://ai.test", {}, "pro", None, "Hola", db_factory, asyncio.Queue()
    )
    recorded.assert_awaited_once_with("db", "pro", ai_cost_micros(usage))


@pytest.fixture
def insights(monkeypatch):
    state = SimpleNamespace(status=200, use=None)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return SimpleNamespace(status_code=state.status, json=lambda: {"patterns": []})

    take = AsyncMock(return_value=usage_service.AIUse(pro=False, left=4))
    give_back = AsyncMock()
    monkeypatch.setattr(ai_routes, "take_ai_use", take)
    monkeypatch.setattr(ai_routes, "give_back_ai_use", give_back)
    monkeypatch.setattr(ai_routes.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        ai_routes,
        "BehavioralAnalyzer",
        lambda db: SimpleNamespace(
            collect_signals=AsyncMock(
                return_value={
                    "hour_buckets": [], "task_stats": {}, "session_stats": {},
                    "top_productive_hours": [], "work_style_hint": "",
                }
            )
        ),
    )
    monkeypatch.setattr(
        ai_routes, "UsersRepository", lambda db: SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock

    from app.database import get_db
    from app.routes.common import get_current_user_id

    app = FastAPI()
    app.include_router(ai_routes.router)
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(subscriptionStatus="free"))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    return TestClient(app), state, take, give_back


def test_insights_analysis_counts_as_an_ai_use(insights):
    client, _, take, give_back = insights
    response = client.post("/ai/analyze-patterns")
    assert response.status_code == 200
    take.assert_awaited_once()
    give_back.assert_not_awaited()
    assert response.headers["X-AI-Messages-Remaining"] == "4"


def test_a_failed_insights_analysis_gives_the_use_back(insights):
    client, state, _, give_back = insights
    state.status = 500
    response = client.post("/ai/analyze-patterns")
    assert response.status_code == 500
    give_back.assert_awaited_once()
