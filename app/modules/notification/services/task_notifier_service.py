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
import uuid
from datetime import datetime

from app.database import async_session_local
from app.models import Task, Notification
from app.sockets.realtime import sio
from app.modules.task.repository import TasksRepository
from app.modules.notification.repository import NotificationsRepository


def _task_start_at(task: Task) -> datetime:
    return task.estimated_start_date or task.deadline


async def _check_and_notify_once() -> None:
    """Run a single notification sweep across all active users and tasks."""
    now = datetime.utcnow()

    async with async_session_local() as db:
        tasks_repo = TasksRepository(db)
        notif_repo = NotificationsRepository(db)

        # ── 5-minute warning ──────────────────────────────────────────────
        # Tasks whose start time falls in [now+4min, now+6min] and haven't
        # been notified yet for the 5-min window.
        tasks_5min = await tasks_repo.get_tasks_for_warning(4.0, 6.0, is_last_minute=False)

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
            
            # Save notification in the database
            notif_item = Notification(
                id=str(uuid.uuid4()),
                userId=task.userId,
                relatedTaskId=task.id,
                type="info",
                scheduledAt=start_at,
                status="unread",
                title="Tarea próxima",
                body=f"Tu tarea {task.title}, está a punto de comenzar.",
            )
            await notif_repo.create(notif_item, commit=False)

            task.notified = True
            await tasks_repo.save(task, commit=False)

        # ── 1-minute warning ──────────────────────────────────────────────
        tasks_1min = await tasks_repo.get_tasks_for_warning(0.0, 2.0, is_last_minute=True)

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
            
            # Save notification in the database
            notif_item = Notification(
                id=str(uuid.uuid4()),
                userId=task.userId,
                relatedTaskId=task.id,
                type="warning",
                scheduledAt=start_at,
                status="unread",
                title="¡Tarea urgente!",
                body=f"Tu tarea {task.title}, está a punto de comenzar.",
            )
            await notif_repo.create(notif_item, commit=False)

            task.lastMinuteNotified = True
            await tasks_repo.save(task, commit=False)

        # Commit all notifications and task status changes atomically
        if tasks_5min or tasks_1min:
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
    except Exception:
        pass


async def run_task_notifier_loop() -> None:
    """
    Background loop that runs every 60 seconds.
    Call this once at application startup (see main.py lifespan).
    """
    while True:
        try:
            await _check_and_notify_once()
        except Exception:
            pass
        await asyncio.sleep(60)
