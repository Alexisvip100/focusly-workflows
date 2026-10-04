import datetime as dt
from typing import Any

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Conversation, Message, ProjectGroup, Workspace, Task, User
from app.modules.task.services.scheduler.scheduler_service import (
    work_hours_from_settings,
)
from .prompts import SYSTEM_PROMPT
from .memory import search_memories

# How much of the task list goes into every prompt. All tasks with full notes
# grew without bound (slower, costlier replies); finished work only matters
# while it's recent.
MAX_ACTIVE_TASKS = 120
MAX_RECENT_DONE_TASKS = 20
RECENT_DONE_DAYS = 7
NOTES_PREVIEW_CHARS = 280
MAX_SUBTASKS_LISTED = 12

_DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def describe_work_hours(settings: dict[str, Any] | None) -> str:
    """The user's work days and hours from their profile, for scheduling."""
    config = work_hours_from_settings(settings)
    days = [str(d).lower()[:3] for d in config.get("selectedDays") or []]
    days = [d for d in _DAY_ORDER if d in days] or _DAY_ORDER[:5]
    start = config.get("startTime") or "09:00"
    end = config.get("endTime") or "17:00"
    return f"{', '.join(d.capitalize() for d in days)} · {start} - {end}"


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def select_context_tasks(tasks: list[Any], now: dt.datetime) -> tuple[list[Any], int]:
    """Open tasks plus recently finished ones; returns (tasks, omitted count)."""
    recent_cutoff = now - dt.timedelta(days=RECENT_DONE_DAYS)
    active, done = [], []
    for task in tasks:
        status = (task.status or "").lower()
        if status == "archived":
            continue
        if status == "done":
            finished = task.completedAt or task.updatedAt
            if finished and finished >= recent_cutoff:
                done.append(task)
            continue
        active.append(task)
    omitted = max(0, len(active) - MAX_ACTIVE_TASKS)
    return active[:MAX_ACTIVE_TASKS] + done[:MAX_RECENT_DONE_TASKS], omitted


def format_subtasks(subtasks: Any) -> str | None:
    if not isinstance(subtasks, list) or not subtasks:
        return None
    parts = []
    for sub in subtasks[:MAX_SUBTASKS_LISTED]:
        if not isinstance(sub, dict):
            continue
        mark = "x" if sub.get("completed") else " "
        title = _one_line(sub.get("title")) or "(untitled)"
        minutes = sub.get("estimate_timer")
        parts.append(f"[{mark}] {title}" + (f" ({minutes}m)" if minutes else ""))
    extra = len(subtasks) - MAX_SUBTASKS_LISTED
    if extra > 0:
        parts.append(f"+{extra} more")
    return "; ".join(parts) if parts else None


def format_task(task: Any) -> str:
    def iso(value: Any) -> str:
        return value.isoformat() if value else "None"

    source_info = f"Source: {task.source or 'focusly'}"
    if task.google_event_id:
        source_info += " (Synced from Google Calendar)"
    notes = _truncate(_one_line(task.notes), NOTES_PREVIEW_CHARS)

    lines = [
        f"- ID: {task.id}",
        f"  Title: {_one_line(task.title)}",
        f"  Status: {task.status}",
        f"  Priority: {task.priorityLevel}",
        f"  Start: {iso(task.estimated_start_date)}",
        f"  End: {iso(task.estimated_end_date)}",
        f"  Deadline: {iso(task.deadline)}",
        f"  {source_info}",
    ]
    if getattr(task, "projectId", None):
        lines.append(f"  Project Group ID: {task.projectId}")
    if getattr(task, "workspaceId", None):
        lines.append(f"  Linked Workspace ID: {task.workspaceId}")
    subtasks = format_subtasks(getattr(task, "subtasks", None))
    if subtasks:
        lines.append(f"  Subtasks: {subtasks}")
    lines.append(f"  Notes/Description: {notes or 'None'}")
    return "\n".join(lines) + "\n\n"


MAX_EVENT_GUESTS_LISTED = 15


def _has_meet(event: dict[str, Any]) -> bool:
    if event.get("hangoutLink"):
        return True
    entry_points = (event.get("conferenceData") or {}).get("entryPoints") or []
    return any("meet.google.com" in (e.get("uri") or "") for e in entry_points)


def format_calendar_event(event: dict[str, Any]) -> str:
    """A Google Calendar event as Lumina sees it: enough to edit it safely
    (who's invited, whether it has a Meet, whether the user organizes it)."""
    start = event.get("start") or {}
    end = event.get("end") or {}
    organizer = event.get("organizer") or {}
    description = _truncate(_one_line(event.get("description")), NOTES_PREVIEW_CHARS)

    lines = [
        f"- ID: {event.get('id') or 'None'}",
        f"  Title: {_one_line(event.get('summary')) or 'Sin título'}",
        "  Source: Google Calendar (Virtual Event)",
        f"  Start: {start.get('dateTime') or start.get('date') or 'None'}",
        f"  End: {end.get('dateTime') or end.get('date') or 'None'}",
        f"  All Day: {'Yes' if start.get('date') else 'No'}",
        f"  Google Meet: {'Yes' if _has_meet(event) else 'No'}",
        "  Organizer: "
        + (
            "the user" if organizer.get("self") else organizer.get("email") or "Unknown"
        ),
    ]
    if event.get("location"):
        lines.append(f"  Location: {_one_line(event['location'])}")

    guests = [
        a
        for a in event.get("attendees") or []
        if isinstance(a, dict) and a.get("email") and not a.get("self")
    ]
    if guests:
        listed = [
            f"{g['email']} ({g.get('responseStatus') or 'needsAction'})"
            for g in guests[:MAX_EVENT_GUESTS_LISTED]
        ]
        extra = len(guests) - MAX_EVENT_GUESTS_LISTED
        if extra > 0:
            listed.append(f"+{extra} more")
        lines.append(f"  Guests: {', '.join(listed)}")
    lines.append(f"  Notes/Description: {description or 'None'}")
    return "\n".join(lines) + "\n\n"


async def build_context(
    user_id: str,
    conversation_id: str,
    query: str,
    db: AsyncSession,
    client_time: str | None = None,
    time_zone: str | None = None,
) -> str:
    """
    Builds the full prompt context for the LLM.
    """
    now_utc = dt.datetime.now(dt.timezone.utc)
    display_time = client_time or now_utc.strftime("%Y-%m-%d %H:%M")
    tz_info = f" ({time_zone})" if time_zone else " (UTC)"

    # Fetch user profile to get their name
    user_res = await db.execute(select(User).filter(User.id == user_id))
    user = user_res.scalars().first()
    user_name = user.name if user else "Usuario"
    user_settings = user.settings if (user and isinstance(user.settings, dict)) else {}
    is_calendar_connected = bool(
        user
        and (
            user_settings.get("calendarConnected")
            or user.googleRefreshToken
            or user.authProvider == "google"
        )
    )

    context = (
        f"{SYSTEM_PROMPT}\n\n"
        f"--- USER PROFILE ---\n"
        f"- Name: {user_name}\n\n"
        f"--- ENVIRONMENT INFO ---\n"
        f"- Current Local Date/Time: {display_time}{tz_info}\n"
        f"- User Work Days & Hours (from their profile): {describe_work_hours(user_settings)}\n"
        f"- Google Calendar: {'connected' if is_calendar_connected else 'not connected'}\n"
        f"- CRITICAL SCHEDULING CONSTRAINT: Every task scheduled for TODAY must have its start and deadline strictly AFTER the current time ({display_time}). You must NEVER schedule tasks in the past.\n\n"
    )

    # 1. Fetch relevant memories
    memories = await search_memories(user_id, query, db)
    if memories:
        context += f"--- USER MEMORIES ---\n{memories}\n\n"

    # 2. Fetch user's project groups
    groups_result = await db.execute(
        select(ProjectGroup).filter(ProjectGroup.userId == user_id)
    )
    groups = groups_result.scalars().all()
    if groups:
        context += "--- EXISTING PROJECT GROUPS (FOLDERS) ---\n"
        for g in groups:
            context += f"- ID: {g.id}, Name: {g.name}\n"
        context += "\n"

    # 3. Fetch user's workspaces
    ws_result = await db.execute(select(Workspace).filter(Workspace.userId == user_id))
    workspaces = ws_result.scalars().all()
    if workspaces:
        context += "--- EXISTING WORKSPACES (DOCUMENTS) ---\n"
        for w in workspaces:
            context += f"- ID: {w.id}, Title: {w.title}, Project Group ID: {w.groupId or 'None (Ungrouped)'}\n"
        context += "\n"

    # 4. Fetch user's active tasks and calendar events
    tasks_result = await db.execute(
        select(Task)
        .filter(Task.userId == user_id)
        .filter(Task.deletedAt == None)
        .order_by(Task.deadline.asc())
    )
    tasks, omitted = select_context_tasks(
        list(tasks_result.scalars().all()), now_utc.replace(tzinfo=None)
    )
    if tasks:
        context += "--- USER TASKS AND CALENDAR EVENTS ---\n"
        for t in tasks:
            context += format_task(t)
        if omitted:
            context += f"({omitted} more open tasks not listed)\n\n"

    # 4b. Fetch user's Google Calendar events (Virtual / External Calendar Events in Calendar View)
    if is_calendar_connected:
        try:
            import asyncio
            from app.modules.google_calendar.routes import get_google_calendar_service

            gc_service = get_google_calendar_service(db)
            t_min = (now_utc - dt.timedelta(days=7)).isoformat()
            t_max = (now_utc + dt.timedelta(days=45)).isoformat()

            events_data = await asyncio.wait_for(
                gc_service.get_events(user_id, time_min=t_min, time_max=t_max),
                timeout=5.0,
            )
            items = events_data.get("items", [])
            synced_ids = {t.google_event_id for t in tasks if t.google_event_id}

            valid_calendar_events = []
            for item in items:
                if item.get("status") == "cancelled":
                    continue
                ev_id = item.get("id")
                if ev_id and ev_id in synced_ids:
                    continue
                valid_calendar_events.append(item)

            if valid_calendar_events:
                context += "--- GOOGLE CALENDAR EVENTS (SHOWN IN CALENDAR VIEW) ---\n"
                for item in valid_calendar_events:
                    context += format_calendar_event(item)
        except Exception:
            pass

    # 5. Fetch user's productivity insights (weekly stats)
    try:
        from app.modules.insights.services.insights_service import InsightsService

        insights_service = InsightsService(db)
        insights = await insights_service.getInsights(user_id, "Weekly")
        if insights:
            context += "--- USER PRODUCTIVITY INSIGHTS (WEEKLY SUMMARY) ---\n"
            context += f"- Total Focus Hours: {insights.get('totalFocusHours', {}).get('value', 'N/A')}\n"
            context += f"- Task Completion Rate: {insights.get('taskCompletion', {}).get('value', 'N/A')}\n"
            context += f"- Energy/Efficiency Score: {insights.get('energyScore', {}).get('value', 'N/A')}\n"
            context += f"- Golden Window (Most Productive Hours): {insights.get('goldenWindow', {}).get('value', 'N/A')}\n"
            context += (
                f"- Break Time: {insights.get('breakHours', {}).get('value', 'N/A')}\n"
            )

            time_dist = insights.get("timeDistribution", [])
            if time_dist:
                context += "- Time Distribution:\n"
                for item in time_dist:
                    context += f"  * {item.get('name')}: {item.get('value')} minutes\n"

            trends = insights.get("productivityTrends", [])
            if trends:
                context += "- Daily Productivity Trends (Planned vs Actual Hours):\n"
                for t in trends:
                    context += f"  * {t.get('label')}: Planned {t.get('planned')}h, Actual {t.get('actual')}h\n"
            context += "\n"
    except Exception:
        pass

    # 4. Fetch conversation summary
    conv_result = await db.execute(
        select(Conversation).filter(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()

    if conversation and conversation.summary:
        context += f"--- PREVIOUS CONVERSATION SUMMARY ---\n{conversation.summary}\n\n"

    # 3. Fetch recent messages
    if conversation:
        msg_result = await db.execute(
            select(Message)
            .filter(Message.conversationId == conversation_id)
            .order_by(Message.createdAt.desc())
            .limit(10)
        )
        recent_messages = list(msg_result.scalars().all())
        # They come out desc, so reverse them for chronological
        recent_messages.reverse()

        if recent_messages:
            context += "--- RECENT MESSAGES ---\n"
            for m in recent_messages:
                context += f"{m.role}: {m.content}\n"

    context += f"\nUser Query: {query}\n"
    return context
