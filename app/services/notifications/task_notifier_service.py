"""
Task Notifier Service
─────────────────────
Polls the database every minute and emits WebSocket events to connected
frontend clients when a task is about to start on the calendar.

Uses estimated_start_date when set, otherwise falls back to deadline.

Two notification windows:
  • "5-minute warning"  → fires when start is 4-6 min away  (notified flag)
  • "1-minute warning"  → fires when start is 0-2 min away  (lastMinuteNotified flag)

Socket event emitted: "task_upcoming"
Payload: { taskId, title, deadline, minutesLeft, type: "5min" | "1min" }
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update

from app.database import async_session_local
from app.models.models import Task, User
from app.sockets.realtime import sio

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ["completed", "cancelled", "Completed"]
_notification_time = func.coalesce(Task.estimated_start_date, Task.deadline)


def _task_start_at(task: Task) -> datetime:
    return task.estimated_start_date or task.deadline


async def _check_and_notify_once() -> None:
    """Run a single notification sweep across all active users and tasks."""
    now = datetime.utcnow()

    async with async_session_local() as db:
        # ── 5-minute warning ──────────────────────────────────────────────
        # Tasks whose start time falls in [now+4min, now+6min] and haven't
        # been notified yet for the 5-min window.
        result = await db.execute(
            select(Task, User)
            .join(User, User.id == Task.userId)
            .where(
                Task.deletedAt == None,
                Task.status.notin_(_ACTIVE_STATUSES),
                or_(Task.notified == False, Task.notified.is_(None)),
                _notification_time >= now + timedelta(minutes=4),
                _notification_time <= now + timedelta(minutes=6),
            )
        )
        tasks_5min = result.all()

        for task, user in tasks_5min:
            start_at = _task_start_at(task)
            minutes_left = int((start_at - now).total_seconds() / 60)
            await _emit_notification(
                user_id=task.userId,
                task_id=task.id,
                title=task.title,
                start_at=start_at,
                minutes_left=minutes_left,
                notif_type="5min",
            )
            await db.execute(
                update(Task).where(Task.id == task.id).values(notified=True)
            )
            logger.info(
                "[NOTIFIER] 5-min alert sent → user=%s task=%s (%s)",
                task.userId, task.id, task.title,
            )

        # ── 1-minute warning ──────────────────────────────────────────────
        result = await db.execute(
            select(Task, User)
            .join(User, User.id == Task.userId)
            .where(
                Task.deletedAt == None,
                Task.status.notin_(_ACTIVE_STATUSES),
                or_(Task.lastMinuteNotified == False, Task.lastMinuteNotified.is_(None)),
                _notification_time >= now,
                _notification_time <= now + timedelta(minutes=2),
            )
        )
        tasks_1min = result.all()

        for task, user in tasks_1min:
            start_at = _task_start_at(task)
            minutes_left = max(0, int((start_at - now).total_seconds() / 60))
            await _emit_notification(
                user_id=task.userId,
                task_id=task.id,
                title=task.title,
                start_at=start_at,
                minutes_left=minutes_left,
                notif_type="1min",
            )
            await db.execute(
                update(Task).where(Task.id == task.id).values(lastMinuteNotified=True)
            )
            logger.info(
                "[NOTIFIER] 1-min alert sent → user=%s task=%s (%s)",
                task.userId, task.id, task.title,
            )

        await db.commit()


async def _emit_notification(
    user_id: str,
    task_id: str,
    title: str,
    start_at: datetime,
    minutes_left: int,
    notif_type: str,
) -> None:
    """Emit a Socket.io event to the user's room."""
    room = f"user_{user_id}"
    payload = {
        "taskId": task_id,
        "title": title,
        "deadline": start_at.isoformat() + "Z",
        "minutesLeft": minutes_left,
        "type": notif_type,
    }
    try:
        await sio.emit("task_upcoming", payload, room=room, namespace="/realtime")
        logger.debug("[NOTIFIER] Emitted task_upcoming to room %s: %s", room, payload)
    except Exception as exc:
        logger.error("[NOTIFIER] Failed to emit to room %s: %s", room, exc)


async def run_task_notifier_loop() -> None:
    """
    Background loop that runs every 60 seconds.
    Call this once at application startup (see main.py lifespan).
    """
    logger.info("[NOTIFIER] Task notifier loop started.")
    while True:
        try:
            await _check_and_notify_once()
        except Exception as exc:
            logger.error("[NOTIFIER] Unexpected error in sweep: %s", exc)
        await asyncio.sleep(60)
