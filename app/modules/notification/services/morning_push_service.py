"""
The morning summary as a web push: "Buenos días, hoy tienes N tareas", at
7-8 AM in the user's own time zone (the one their devices reported when they
subscribed), once a day, only when there is something for today.

Runs in the smart notifier sweep (every 5 minutes).
"""

import logging
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PushSubscription, Task
from app.modules.notification.services import push_service
from app.redis import cache

logger = logging.getLogger(__name__)

MORNING_HOUR = 7
# Statuses that are finished, not pending, for today's count
CLOSED_STATUSES = ("Done", "Archived")


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def local_day_bounds_utc(now_utc: datetime, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Today, in `zone`, as a naive-UTC [start, end) range (how tasks are
    stored)."""
    local_today = now_utc.replace(tzinfo=timezone.utc).astimezone(zone).date()
    start = datetime.combine(local_today, time(0), tzinfo=zone)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def summary_body(pending: int, high_priority: int) -> str:
    tasks = "1 tarea" if pending == 1 else f"{pending} tareas"
    extra = f" ({high_priority} de prioridad alta)" if high_priority else ""
    return f"Hoy tienes {tasks}{extra}. ¡Vamos!"


async def send_morning_pushes(db: AsyncSession, now: datetime) -> None:
    """`now` is naive UTC, as the smart notifier passes it."""
    if not push_service.is_configured():
        return

    rows = (await db.execute(select(PushSubscription.userId, PushSubscription.timeZone))).all()
    zones: dict[str, set[str]] = defaultdict(set)
    for user_id, tz in rows:
        if tz:
            zones[user_id].add(tz)

    for user_id, tz_names in zones.items():
        # Devices in several zones: the user's first one alphabetically, so
        # the choice is stable from one sweep to the next.
        zone = _zone(sorted(tz_names)[0])
        if zone is None:
            continue
        local_now = now.replace(tzinfo=timezone.utc).astimezone(zone)
        if local_now.hour != MORNING_HOUR:
            continue

        # Once a day per user, across sweeps and replicas. Redis down: skip
        # rather than risk a push every 5 minutes.
        taken = await cache.acquire_lock(
            f"push:morning:{user_id}:{local_now.date().isoformat()}", 26 * 3600
        )
        if not taken:
            continue

        start, end = local_day_bounds_utc(now, zone)
        when = func.coalesce(Task.estimated_start_date, Task.deadline)
        today = (
            Task.userId == user_id,
            Task.deletedAt.is_(None),
            Task.status.notin_(CLOSED_STATUSES),
            when >= start,
            when < end,
        )
        pending = (await db.execute(select(func.count(Task.id)).where(*today))).scalar() or 0
        if not pending:
            continue
        high = (
            await db.execute(
                select(func.count(Task.id)).where(*today, Task.priorityLevel >= 3)
            )
        ).scalar() or 0

        await push_service.send_to_user(
            db,
            user_id,
            "☀️ Buenos días",
            summary_body(pending, high),
            url="/dashboard",
            tag="morning-summary",
            # Stale by noon
            ttl=4 * 60 * 60,
        )
