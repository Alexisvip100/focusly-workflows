from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.plans import (
    FREE_AI_MESSAGE_LIMIT,
    PRO_DAILY_AI_LIMIT,
    PRO_MONTHLY_AI_COST_CAP_USD,
    is_pro,
)
from app.modules.user.domain.entities.user import User

# AI use, counted on the user row so deleting conversations (or clearing the
# browser) doesn't give it back. Each count is one statement, so two tabs
# sending at once can't both get the last message. A count for another month
# (or day) than the current one starts over in that same statement.


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def day_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


# When the counts start over, as exact instants (ISO, UTC): the app shows
# them in each user's own time zone and language, wherever they are.


def month_resets_at(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc).isoformat()


def day_resets_at(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return (start + timedelta(days=1)).isoformat()


async def _count_one(db: AsyncSession, statement) -> int | None:
    result = await db.execute(
        statement.execution_options(synchronize_session=False)
    )
    count = result.scalar_one_or_none()
    await db.commit()
    return count


async def consume_ai_message(
    db: AsyncSession, user_id: str, now: datetime | None = None
) -> int | None:
    """Counts one free AI message this month. Returns the month's total, or
    None when the limit was already reached."""
    period = month_key(now)
    same_month = User.aiPeriod == period
    used = func.coalesce(User.aiMessagesUsed, 0)
    return await _count_one(
        db,
        update(User)
        .where(
            User.id == user_id,
            or_(User.aiPeriod.is_(None), User.aiPeriod != period, used < FREE_AI_MESSAGE_LIMIT),
        )
        .values(
            aiMessagesUsed=case((same_month, used + 1), else_=1),
            aiCostMicros=case((same_month, func.coalesce(User.aiCostMicros, 0)), else_=0),
            aiPeriod=period,
        )
        .returning(User.aiMessagesUsed),
    )


async def refund_ai_message(
    db: AsyncSession, user_id: str, now: datetime | None = None
) -> None:
    """Gives back a message counted for a request that was then rejected."""
    used = func.coalesce(User.aiMessagesUsed, 0)
    await db.execute(
        update(User)
        .where(User.id == user_id, User.aiPeriod == month_key(now), used > 0)
        .values(aiMessagesUsed=used - 1)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def consume_daily_ai_use(
    db: AsyncSession, user_id: str, now: datetime | None = None
) -> int | None:
    """Counts one Pro AI use today. Returns the day's total, or None when the
    fair-use limit was already reached."""
    day = day_key(now)
    same_day = User.aiDailyDate == day
    used = func.coalesce(User.aiDailyUsed, 0)
    return await _count_one(
        db,
        update(User)
        .where(
            User.id == user_id,
            or_(User.aiDailyDate.is_(None), User.aiDailyDate != day, used < PRO_DAILY_AI_LIMIT),
        )
        .values(aiDailyUsed=case((same_day, used + 1), else_=1), aiDailyDate=day)
        .returning(User.aiDailyUsed),
    )


async def refund_daily_ai_use(
    db: AsyncSession, user_id: str, now: datetime | None = None
) -> None:
    used = func.coalesce(User.aiDailyUsed, 0)
    await db.execute(
        update(User)
        .where(User.id == user_id, User.aiDailyDate == day_key(now), used > 0)
        .values(aiDailyUsed=used - 1)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def add_ai_cost(
    db: AsyncSession, user_id: str, micros: int, now: datetime | None = None
) -> None:
    """Adds what a reply cost to the user's month."""
    if micros <= 0:
        return
    period = month_key(now)
    same_month = User.aiPeriod == period
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            aiCostMicros=case(
                (same_month, func.coalesce(User.aiCostMicros, 0) + micros), else_=micros
            ),
            aiMessagesUsed=case((same_month, func.coalesce(User.aiMessagesUsed, 0)), else_=0),
            aiPeriod=period,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()


# Reading the counts back: a count from another month (or day) is zero. Any
# object with the fields will do (status code also gets plain records).


def messages_used_this_month(user: Any, now: datetime | None = None) -> int:
    if getattr(user, "aiPeriod", None) != month_key(now):
        return 0
    return int(getattr(user, "aiMessagesUsed", 0) or 0)


def cost_this_month_usd(user: Any, now: datetime | None = None) -> float:
    if getattr(user, "aiPeriod", None) != month_key(now):
        return 0.0
    return int(getattr(user, "aiCostMicros", 0) or 0) / 1_000_000


def daily_uses_today(user: Any, now: datetime | None = None) -> int:
    if getattr(user, "aiDailyDate", None) != day_key(now):
        return 0
    return int(getattr(user, "aiDailyUsed", 0) or 0)


@dataclass
class AIUse:
    """One AI request counted against the user's plan."""

    pro: bool
    # Free: messages left this month. Pro: uses left today.
    left: int
    # Pro past its monthly cost cap: answer with the cheaper model
    economy: bool = False

    def headers(self) -> dict[str, str]:
        name = "X-AI-Daily-Remaining" if self.pro else "X-AI-Messages-Remaining"
        return {name: str(self.left)}


async def take_ai_use(db: AsyncSession, user_id: str, user: Any) -> AIUse:
    """Counts one AI request for the user's plan, or refuses it: 402 when the
    free messages of the month are used up (the app offers Pro), 429 when a
    Pro account reaches today's fair-use limit."""
    if is_pro(user):
        used_today = await consume_daily_ai_use(db, user_id)
        if used_today is None:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "daily_limit_reached",
                    "limit": PRO_DAILY_AI_LIMIT,
                    "resets_at": day_resets_at(),
                },
            )
        return AIUse(
            pro=True,
            left=PRO_DAILY_AI_LIMIT - used_today,
            economy=cost_this_month_usd(user) >= PRO_MONTHLY_AI_COST_CAP_USD,
        )
    used = await consume_ai_message(db, user_id)
    if used is None:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "free_limit_reached",
                "limit": FREE_AI_MESSAGE_LIMIT,
                "resets_at": month_resets_at(),
            },
        )
    return AIUse(pro=False, left=FREE_AI_MESSAGE_LIMIT - used)


async def give_back_ai_use(db: AsyncSession, user_id: str, use: AIUse) -> None:
    """For a counted request that then failed."""
    if use.pro:
        await refund_daily_ai_use(db, user_id)
    else:
        await refund_ai_message(db, user_id)
