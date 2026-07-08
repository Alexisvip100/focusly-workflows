"""
Smart Notifier Service
──────────────────────
Background service that generates intelligent notifications based on
user activity patterns: overdue tasks, productivity streaks, daily
summaries, focus session completions, break reminders, achievements, etc.

Runs every 5 minutes. Each check includes anti-duplicate logic to
prevent notification spam.
"""

import asyncio
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, cast, Date
from sqlalchemy.sql import extract

from app.database import async_session_local
from app.models import Task, User, FocusSession, Notification
import logging

logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _already_notified(db, user_id: str, notif_type: str, since: datetime) -> bool:
    """Check if a notification of this type was already created for this user since a given time."""
    result = await db.execute(
        select(Notification.id)
        .where(
            Notification.userId == user_id,
            Notification.type == notif_type,
            Notification.createdAt >= since,
        )
        .limit(1)
    )
    return result.scalars().first() is not None


async def _already_notified_for_task(
    db, user_id: str, task_id: str, notif_type: str
) -> bool:
    """Check if a notification was already created for a specific task + type."""
    result = await db.execute(
        select(Notification.id)
        .where(
            Notification.userId == user_id,
            Notification.relatedTaskId == task_id,
            Notification.type == notif_type,
        )
        .limit(1)
    )
    return result.scalars().first() is not None


def _save_notif(
    db,
    user_id: str,
    title: str,
    body: str,
    notif_type: str,
    scheduled_at: datetime | None = None,
    task_id: str | None = None,
):
    """Add a Notification object to the session (caller must commit)."""
    item = Notification(
        id=str(uuid.uuid4()),
        userId=user_id,
        relatedTaskId=task_id,
        type=notif_type,
        scheduledAt=scheduled_at or datetime.utcnow(),
        status="unread",
        title=title,
        body=body,
    )
    db.add(item)


# ─── 1. Tareas vencidas sin completar ────────────────────────────────────────


async def _check_overdue_tasks(db, now: datetime) -> None:
    """Notify users about tasks past their deadline that are not completed."""
    result = await db.execute(
        select(Task).where(
            Task.deletedAt == None,
            Task.status.notin_(["completed", "Completed", "cancelled"]),
            Task.deadline < now,
            Task.deadline >= now - timedelta(hours=24),
        )
    )
    tasks = result.scalars().all()

    for task in tasks:
        if await _already_notified_for_task(db, task.userId, task.id, "overdue"):
            continue
        hours_ago = int((now - task.deadline).total_seconds() / 3600)
        time_str = f"hace {hours_ago}h" if hours_ago > 0 else "recientemente"
        _save_notif(
            db,
            task.userId,
            title="⚠️ Tarea vencida",
            body=f'Tu tarea "{task.title}" venció {time_str} y sigue pendiente.',
            notif_type="overdue",
            scheduled_at=task.deadline,
            task_id=task.id,
        )


# ─── 2. Racha de productividad ───────────────────────────────────────────────


async def _check_productivity_streak(db, now: datetime) -> None:
    """Notify users who completed all tasks for 3+ consecutive days."""
    today = now.date()
    if await _already_notified(
        db, "__all__", "streak_check", datetime.combine(today, datetime.min.time())
    ):
        return

    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        if await _already_notified(
            db, user_id, "streak", datetime.combine(today, datetime.min.time())
        ):
            continue

        streak = 0
        for days_back in range(1, 8):
            check_date = today - timedelta(days=days_back)
            total_result = await db.execute(
                select(func.count(Task.id)).where(
                    Task.userId == user_id,
                    Task.deletedAt == None,
                    cast(Task.deadline, Date) == check_date,
                )
            )
            total = total_result.scalar() or 0
            if total == 0:
                break

            completed_result = await db.execute(
                select(func.count(Task.id)).where(
                    Task.userId == user_id,
                    Task.deletedAt == None,
                    Task.status.in_(["completed", "Completed"]),
                    cast(Task.deadline, Date) == check_date,
                )
            )
            completed = completed_result.scalar() or 0
            if completed >= total:
                streak += 1
            else:
                break

        if streak >= 3:
            _save_notif(
                db,
                user_id,
                title="🔥 ¡Racha de productividad!",
                body=f"¡Llevas {streak} días consecutivos completando todas tus tareas!",
                notif_type="streak",
            )


# ─── 3. Resumen diario matutino ──────────────────────────────────────────────


async def _check_daily_summary(db, now: datetime) -> None:
    """Send a morning summary between 7:00-8:00 AM."""
    if not (7 <= now.hour < 8):
        return

    today = now.date()
    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        if await _already_notified(
            db, user_id, "daily_summary", datetime.combine(today, datetime.min.time())
        ):
            continue

        pending_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                Task.status.notin_(["completed", "Completed", "cancelled"]),
                cast(Task.deadline, Date) == today,
            )
        )
        pending = pending_result.scalar() or 0

        high_priority_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                Task.status.notin_(["completed", "Completed", "cancelled"]),
                cast(Task.deadline, Date) == today,
                Task.priorityLevel >= 3,
            )
        )
        high_priority = high_priority_result.scalar() or 0

        if pending > 0:
            hp_text = (
                f", {high_priority} de prioridad alta" if high_priority > 0 else ""
            )
            _save_notif(
                db,
                user_id,
                title="📋 Buenos días",
                body=f"Hoy tienes {pending} tareas pendientes{hp_text}. ¡A por todas!",
                notif_type="daily_summary",
            )


# ─── 4. Horas doradas detectadas ─────────────────────────────────────────────


async def _check_golden_hours(db, now: datetime) -> None:
    """Detect peak productivity hours based on task completion patterns (weekly)."""
    if now.weekday() != 0:  # Only on Mondays
        return

    today = now.date()
    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        if await _already_notified(
            db, user_id, "golden_hours", datetime.combine(today, datetime.min.time())
        ):
            continue

        week_ago = now - timedelta(days=7)
        result = await db.execute(
            select(
                extract("hour", Task.completedAt).label("hour"),
                func.count(Task.id).label("cnt"),
            )
            .where(
                Task.userId == user_id,
                Task.completedAt != None,
                Task.completedAt >= week_ago,
            )
            .group_by(extract("hour", Task.completedAt))
            .order_by(func.count(Task.id).desc())
            .limit(1)
        )
        row = result.first()
        if row and row.cnt >= 3:
            peak_hour = int(row.hour)
            end_hour = (peak_hour + 2) % 24
            _save_notif(
                db,
                user_id,
                title="🧠 Horas doradas detectadas",
                body=f"Tu mayor productividad fue entre {peak_hour}:00 y {end_hour}:00. Programa aquí tus tareas más complejas.",
                notif_type="golden_hours",
            )


# ─── 5. Baja productividad semanal ───────────────────────────────────────────


async def _check_weekly_low_productivity(db, now: datetime) -> None:
    """Compare this week's completions vs last week (Mondays only)."""
    if now.weekday() != 0:
        return

    today = now.date()
    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        if await _already_notified(
            db,
            user_id,
            "low_productivity",
            datetime.combine(today, datetime.min.time()),
        ):
            continue

        this_week_start = today - timedelta(days=7)
        last_week_start = today - timedelta(days=14)

        this_week_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.userId == user_id,
                Task.status.in_(["completed", "Completed"]),
                Task.completedAt
                >= datetime.combine(this_week_start, datetime.min.time()),
                Task.completedAt < datetime.combine(today, datetime.min.time()),
            )
        )
        this_week = this_week_result.scalar() or 0

        last_week_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.userId == user_id,
                Task.status.in_(["completed", "Completed"]),
                Task.completedAt
                >= datetime.combine(last_week_start, datetime.min.time()),
                Task.completedAt
                < datetime.combine(this_week_start, datetime.min.time()),
            )
        )
        last_week = last_week_result.scalar() or 0

        if last_week > 0 and this_week < last_week * 0.6:
            pct = int((1 - this_week / last_week) * 100)
            _save_notif(
                db,
                user_id,
                title="📉 Productividad baja esta semana",
                body=f"Completaste {pct}% menos tareas que la semana anterior. ¿Necesitas reorganizar tu agenda?",
                notif_type="low_productivity",
            )


# ─── 6. Meta semanal alcanzada ────────────────────────────────────────────────


async def _check_weekly_goal(db, now: datetime) -> None:
    """Congratulate user when they complete 15+ tasks this week."""
    today = now.date()
    week_start = today - timedelta(days=today.weekday())

    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        if await _already_notified(
            db,
            user_id,
            "weekly_goal",
            datetime.combine(week_start, datetime.min.time()),
        ):
            continue

        result = await db.execute(
            select(func.count(Task.id)).where(
                Task.userId == user_id,
                Task.status.in_(["completed", "Completed"]),
                Task.completedAt >= datetime.combine(week_start, datetime.min.time()),
            )
        )
        completed = result.scalar() or 0

        if completed >= 15:
            _save_notif(
                db,
                user_id,
                title="🏆 ¡Meta semanal alcanzada!",
                body=f"¡Increíble! Completaste {completed} tareas esta semana. ¡Sigue así!",
                notif_type="weekly_goal",
            )


# ─── 7. Sesión de enfoque completada ─────────────────────────────────────────


async def _check_completed_focus_sessions(db, now: datetime) -> None:
    """Notify about successfully completed focus sessions not yet notified."""
    one_hour_ago = now - timedelta(hours=1)
    result = await db.execute(
        select(FocusSession).where(
            FocusSession.wasSuccessful == True,
            FocusSession.endedAt >= one_hour_ago,
            FocusSession.endedAt <= now,
        )
    )
    sessions = result.scalars().all()

    for session in sessions:
        notif_key = f"focus_complete_{session.id}"
        exists = await db.execute(
            select(Notification.id)
            .where(
                Notification.userId == session.userId,
                Notification.relatedTaskId == notif_key,
            )
            .limit(1)
        )
        if exists.scalars().first():
            continue

        _save_notif(
            db,
            session.userId,
            title="🎯 Sesión de enfoque completada",
            body=f"¡Buen trabajo! Completaste una sesión de enfoque de {session.durationMinutes} minutos.",
            notif_type="success",
            task_id=notif_key,
        )


# ─── 8. Recordatorio de descanso ─────────────────────────────────────────────


async def _check_break_reminder(db, now: datetime) -> None:
    """Remind user to take a break after 120+ minutes of focus sessions today."""
    today_start = datetime.combine(now.date(), datetime.min.time())

    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        if await _already_notified(db, user_id, "break_reminder", today_start):
            continue

        result = await db.execute(
            select(func.sum(FocusSession.durationMinutes)).where(
                FocusSession.userId == user_id,
                FocusSession.endedAt >= today_start,
            )
        )
        total_minutes = result.scalar() or 0

        if total_minutes >= 120:
            # Check if there was a gap >= 30 min between sessions
            sessions_result = await db.execute(
                select(FocusSession)
                .where(
                    FocusSession.userId == user_id,
                    FocusSession.endedAt >= today_start,
                )
                .order_by(FocusSession.startedAt.asc())
            )
            sessions = sessions_result.scalars().all()

            had_break = False
            for i in range(1, len(sessions)):
                gap = (
                    sessions[i].startedAt - sessions[i - 1].endedAt
                ).total_seconds() / 60
                if gap >= 30:
                    had_break = True
                    break

            if not had_break:
                _save_notif(
                    db,
                    user_id,
                    title="🧘 Hora de un descanso",
                    body=f"Llevas {int(total_minutes)} minutos de enfoque hoy sin una pausa larga. Te recomendamos 10 minutos de descanso.",
                    notif_type="break_reminder",
                )


# ─── 9. Focus Shield activado ────────────────────────────────────────────────


async def _check_focus_shield(db, now: datetime) -> None:
    """Summarize distraction blocks for the day if count > 5."""
    today_start = datetime.combine(now.date(), datetime.min.time())

    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        if await _already_notified(db, user_id, "focus_shield", today_start):
            continue

        result = await db.execute(
            select(func.sum(FocusSession.distractionCount)).where(
                FocusSession.userId == user_id,
                FocusSession.endedAt >= today_start,
            )
        )
        total_distractions = result.scalar() or 0

        if total_distractions > 5:
            _save_notif(
                db,
                user_id,
                title="🛡️ Focus Shield activado",
                body=f"Tu escudo de enfoque bloqueó {total_distractions} intentos de distracción hoy. ¡Mantén el enfoque!",
                notif_type="focus_shield",
            )


# ─── 12. Logros desbloqueados ─────────────────────────────────────────────────

_ACHIEVEMENTS = [
    {
        "key": "early_bird",
        "title": "⭐ Logro: Madrugador",
        "body": "¡Completaste 5 tareas antes de las 9:00 AM! Eres un madrugador nato.",
        "check": "early_completions",
        "threshold": 5,
    },
    {
        "key": "focus_master",
        "title": "⭐ Logro: Maestro del enfoque",
        "body": "¡Completaste 10 sesiones de enfoque exitosas! Tu concentración es admirable.",
        "check": "focus_sessions",
        "threshold": 10,
    },
    {
        "key": "task_machine",
        "title": "⭐ Logro: Máquina de tareas",
        "body": "¡Has completado 50 tareas en total! Eres imparable.",
        "check": "total_completed",
        "threshold": 50,
    },
    {
        "key": "zero_distractions",
        "title": "⭐ Logro: Enfoque total",
        "body": "¡Completaste 5 sesiones de enfoque seguidas con 0 distracciones!",
        "check": "zero_distraction_sessions",
        "threshold": 5,
    },
    {
        "key": "week_warrior",
        "title": "⭐ Logro: Guerrero semanal",
        "body": "¡Completaste 25 tareas en una sola semana! Productividad increíble.",
        "check": "weekly_completed",
        "threshold": 25,
    },
]


async def _check_achievements(db, now: datetime) -> None:
    """Check if users hit achievement thresholds."""
    users_result = await db.execute(select(User.id))
    user_ids = [uid for (uid,) in users_result.all()]

    for user_id in user_ids:
        for achievement in _ACHIEVEMENTS:
            notif_key = f"achievement_{achievement['key']}"
            exists = await db.execute(
                select(Notification.id)
                .where(
                    Notification.userId == user_id,
                    Notification.relatedTaskId == notif_key,
                )
                .limit(1)
            )
            if exists.scalars().first():
                continue

            count = 0
            check = achievement["check"]

            if check == "early_completions":
                r = await db.execute(
                    select(func.count(Task.id)).where(
                        Task.userId == user_id,
                        Task.status.in_(["completed", "Completed"]),
                        Task.completedAt != None,
                        extract("hour", Task.completedAt) < 9,
                    )
                )
                count = r.scalar() or 0

            elif check == "focus_sessions":
                r = await db.execute(
                    select(func.count(FocusSession.id)).where(
                        FocusSession.userId == user_id,
                        FocusSession.wasSuccessful == True,
                    )
                )
                count = r.scalar() or 0

            elif check == "total_completed":
                r = await db.execute(
                    select(func.count(Task.id)).where(
                        Task.userId == user_id,
                        Task.status.in_(["completed", "Completed"]),
                    )
                )
                count = r.scalar() or 0

            elif check == "zero_distraction_sessions":
                r = await db.execute(
                    select(func.count(FocusSession.id)).where(
                        FocusSession.userId == user_id,
                        FocusSession.wasSuccessful == True,
                        FocusSession.distractionCount == 0,
                    )
                )
                count = r.scalar() or 0

            elif check == "weekly_completed":
                today = now.date()
                week_start = today - timedelta(days=today.weekday())
                r = await db.execute(
                    select(func.count(Task.id)).where(
                        Task.userId == user_id,
                        Task.status.in_(["completed", "Completed"]),
                        Task.completedAt
                        >= datetime.combine(week_start, datetime.min.time()),
                    )
                )
                count = r.scalar() or 0

            if count >= achievement["threshold"]:
                _save_notif(
                    db,
                    user_id,
                    title=achievement["title"],
                    body=achievement["body"],
                    notif_type="achievement",
                    task_id=notif_key,
                )


# ─── Main Loop ────────────────────────────────────────────────────────────────


async def _run_smart_checks_once() -> None:
    """Execute all smart notification checks in a single sweep."""
    now = datetime.utcnow()

    checks = [
        ("overdue_tasks", _check_overdue_tasks),
        ("productivity_streak", _check_productivity_streak),
        ("daily_summary", _check_daily_summary),
        ("golden_hours", _check_golden_hours),
        ("weekly_low_productivity", _check_weekly_low_productivity),
        ("weekly_goal", _check_weekly_goal),
        ("completed_focus_sessions", _check_completed_focus_sessions),
        ("break_reminder", _check_break_reminder),
        ("focus_shield", _check_focus_shield),
        ("achievements", _check_achievements),
    ]

    async with async_session_local() as db:
        for check_name, check in checks:
            try:
                await check(db, now)
            except Exception:
                logger.exception(
                    "Smart notifier check '%s' failed",
                    check_name,
                )

        try:
            await db.commit()
        except Exception:
            logger.exception("Failed to commit smart notification sweep")
            await db.rollback()


async def run_smart_notifier_loop() -> None:
    """
    Background loop that runs every 5 minutes.
    Call this once at application startup (see main.py lifespan).
    """
    while True:
        try:
            await _run_smart_checks_once()
        except Exception:
            pass
        await asyncio.sleep(300)  # 5 minutes
