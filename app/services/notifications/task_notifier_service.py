"""
Task Notifier Service
─────────────────────
Polls the database every minute and emits WebSocket events to connected
frontend clients when a task's deadline is approaching.

Two notification windows:
  • "5-minute warning"  → fires when deadline is 4-6 min away  (notified flag)
  • "1-minute warning"  → fires when deadline is 0-2 min away  (lastMinuteNotified flag)

Socket event emitted: "task_upcoming"
Payload: { taskId, title, deadline, minutesLeft, type: "5min" | "1min" }
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_local
from app.models.models import Task, User
from app.sockets.realtime import sio

logger = logging.getLogger(__name__)


async def _check_and_notify_once() -> None:
    """Run a single notification sweep across all active users and tasks."""
    now = datetime.utcnow()
    five_min_from_now = now + timedelta(minutes=5)
    one_min_from_now  = now + timedelta(minutes=1)

    async with async_session_local() as db:
        # ── 5-minute warning ──────────────────────────────────────────────
        # Tasks whose deadline falls in [now+4min, now+6min] and haven't been
        # notified yet for the 5-min window.
        result = await db.execute(
            select(Task, User)
            .join(User, User.id == Task.userId)
            .where(
                Task.deletedAt == None,
                Task.status.notin_(["completed", "cancelled", "Completed"]),
                Task.notified == False,
                Task.deadline >= now + timedelta(minutes=4),
                Task.deadline <= now + timedelta(minutes=6),
            )
        )
        tasks_5min = result.all()

        for task, user in tasks_5min:
            minutes_left = int((task.deadline - now).total_seconds() / 60)
            await _emit_notification(
                user_id=task.userId,
                task_id=task.id,
                title=task.title,
                deadline=task.deadline,
                minutes_left=minutes_left,
                notif_type="5min",
            )
            # Mark as notified so we don't fire again
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
                Task.status.notin_(["completed", "cancelled", "Completed"]),
                Task.lastMinuteNotified == False,
                Task.deadline >= now,
                Task.deadline <= one_min_from_now + timedelta(minutes=1),
            )
        )
        tasks_1min = result.all()

        for task, user in tasks_1min:
            minutes_left = max(0, int((task.deadline - now).total_seconds() / 60))
            await _emit_notification(
                user_id=task.userId,
                task_id=task.id,
                title=task.title,
                deadline=task.deadline,
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
    deadline: datetime,
    minutes_left: int,
    notif_type: str,
) -> None:
    """Emit a Socket.io event to the user's room."""
    room = f"user_{user_id}"
    payload = {
        "taskId": task_id,
        "title": title,
        "deadline": deadline.isoformat() + "Z",
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
