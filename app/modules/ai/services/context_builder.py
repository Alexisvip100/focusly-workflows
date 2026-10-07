import asyncio
import datetime as dt
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Conversation, ProjectGroup, Workspace, Task, User
from app.modules.task.services.scheduler.scheduler_service import (
    work_hours_from_settings,
)
from app.redis import cache
from .prompts import ONE_SHOT_PROMPT, SYSTEM_PROMPT
from .memory import search_memories

logger = logging.getLogger(__name__)

# How much of the task list goes into every prompt. All tasks with full notes
# grew without bound (slower, costlier replies); finished work only matters
# while it's recent.
MAX_ACTIVE_TASKS = 120
MAX_RECENT_DONE_TASKS = 20
RECENT_DONE_DAYS = 7
NOTES_PREVIEW_CHARS = 280
MAX_SUBTASKS_LISTED = 12
# Every task goes in as one index line; full details (notes, subtasks) only
# for the ones this message is about or that are due soon.
MAX_DETAILED_TASKS = 15
DUE_SOON_DAYS = 3

# Google Calendar, read at most every few minutes (and again right after
# Lumina changes an event): one fetch per message was slow and repetitive.
CALENDAR_CACHE_SECONDS = 300
CALENDAR_PAST_DAYS = 2
CALENDAR_AHEAD_DAYS = 30
CALENDAR_DETAILED_DAYS = 7
MAX_CALENDAR_EVENTS = 120
INSIGHTS_CACHE_SECONDS = 600

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


def _short_dt(value: Any) -> str:
    return value.isoformat(timespec="minutes") if value else ""


def format_task_index(task: Any) -> str:
    """One line per task: enough to refer to it, schedule around it or update
    it. The notes and subtasks go in format_task, for the relevant ones."""
    parts = [
        f"- ID: {task.id}",
        _one_line(task.title) or "(untitled)",
        str(task.status),
        f"P{task.priorityLevel}",
    ]
    start, end = task.estimated_start_date, task.estimated_end_date
    if start or end:
        parts.append(f"{_short_dt(start) or '?'} → {_short_dt(end) or '?'}")
    if task.deadline:
        parts.append(f"due {_short_dt(task.deadline)}")
    if getattr(task, "projectId", None):
        parts.append(f"project {task.projectId}")
    if getattr(task, "workspaceId", None):
        parts.append(f"doc {task.workspaceId}")
    subtasks = getattr(task, "subtasks", None)
    if isinstance(subtasks, list) and subtasks:
        done = sum(1 for s in subtasks if isinstance(s, dict) and s.get("completed"))
        parts.append(f"{done}/{len(subtasks)} subtasks")
    if task.google_event_id:
        parts.append("synced with Google Calendar")
    return " | ".join(parts) + "\n"


def _words(text: str | None) -> set[str]:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", text) if len(w) >= 4}


def pick_detailed_tasks(tasks: list[Any], query: str, now: dt.datetime) -> list[Any]:
    """The tasks the message names (by words of their title or notes), then
    the ones in progress or due within DUE_SOON_DAYS."""
    query_words = _words(query)
    soon = now + dt.timedelta(days=DUE_SOON_DAYS)
    scored = []
    for index, task in enumerate(tasks):
        status = (task.status or "").lower()
        if status == "done":
            continue
        score = 3 * len(query_words & _words(task.title))
        score += len(query_words & _words((task.notes or "")[:NOTES_PREVIEW_CHARS]))
        if "progress" in status:
            score += 1
        if task.deadline and task.deadline <= soon:
            score += 2
        if score:
            scored.append((-score, index, task))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [task for _, _, task in scored[:MAX_DETAILED_TASKS]]


def format_event_brief(event: dict[str, Any]) -> str:
    start = event.get("start") or {}
    end = event.get("end") or {}
    return (
        f"- ID: {event.get('id') or 'None'} | "
        f"{_one_line(event.get('summary')) or 'Sin título'} | "
        f"{start.get('dateTime') or start.get('date') or '?'} → "
        f"{end.get('dateTime') or end.get('date') or '?'}\n"
    )


def calendar_cache_key(user_id: str) -> str:
    return f"ai:calendar:{user_id}"


async def invalidate_calendar_cache(user_id: str) -> None:
    """After an event changes, so Lumina's next answer sees it."""
    await cache.delete(calendar_cache_key(user_id))


async def get_calendar_items(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    """The user's Google events around today, cached for a few minutes."""
    cached = await cache.get(calendar_cache_key(user_id))
    if cached is not None:
        return cached

    from app.modules.google_calendar.routes import get_google_calendar_service

    now_utc = dt.datetime.now(dt.timezone.utc)
    events_data = await asyncio.wait_for(
        get_google_calendar_service(db).get_events(
            user_id,
            time_min=(now_utc - dt.timedelta(days=CALENDAR_PAST_DAYS)).isoformat(),
            time_max=(now_utc + dt.timedelta(days=CALENDAR_AHEAD_DAYS)).isoformat(),
        ),
        timeout=5.0,
    )
    items = [
        item
        for item in events_data.get("items", [])
        if item.get("status") != "cancelled"
    ]
    await cache.set(calendar_cache_key(user_id), items, CALENDAR_CACHE_SECONDS)
    return items


def _event_start(event: dict[str, Any]) -> dt.datetime | None:
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date")
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def format_calendar_events(
    items: list[dict[str, Any]], skip_ids: set[str], now_utc: dt.datetime
) -> str:
    """Events of the coming week in full (guests, Meet…), later ones as one
    line each."""
    detailed_until = now_utc + dt.timedelta(days=CALENDAR_DETAILED_DAYS)
    text = ""
    for event in [e for e in items if e.get("id") not in skip_ids][
        :MAX_CALENDAR_EVENTS
    ]:
        start = _event_start(event)
        if start is None or start <= detailed_until:
            text += format_calendar_event(event)
        else:
            text += format_event_brief(event)
    return text


async def insights_block(db: AsyncSession, user_id: str) -> str:
    """The weekly productivity summary, cached: it changes slowly."""
    key = f"ai:insights:{user_id}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    from app.modules.insights.services.insights_service import InsightsService

    insights = await InsightsService(db).getInsights(user_id, "Weekly")
    text = ""
    if insights:
        text += "--- USER PRODUCTIVITY INSIGHTS (WEEKLY SUMMARY) ---\n"
        text += f"- Total Focus Hours: {insights.get('totalFocusHours', {}).get('value', 'N/A')}\n"
        text += f"- Task Completion Rate: {insights.get('taskCompletion', {}).get('value', 'N/A')}\n"
        text += f"- Energy/Efficiency Score: {insights.get('energyScore', {}).get('value', 'N/A')}\n"
        text += f"- Golden Window (Most Productive Hours): {insights.get('goldenWindow', {}).get('value', 'N/A')}\n"
        text += f"- Break Time: {insights.get('breakHours', {}).get('value', 'N/A')}\n"

        time_dist = insights.get("timeDistribution", [])
        if time_dist:
            text += "- Time Distribution:\n"
            for item in time_dist:
                text += f"  * {item.get('name')}: {item.get('value')} minutes\n"

        trends = insights.get("productivityTrends", [])
        if trends:
            text += "- Daily Productivity Trends (Planned vs Actual Hours):\n"
            for t in trends:
                text += f"  * {t.get('label')}: Planned {t.get('planned')}h, Actual {t.get('actual')}h\n"
        text += "\n"
    await cache.set(key, text, INSIGHTS_CACHE_SECONDS)
    return text


@dataclass
class AIContext:
    """The system prompt, in two parts. `stable` (instructions, profile,
    folders, documents, the task index) repeats from one message to the next,
    so the providers can cache it; `dynamic` (time, memories, calendar, the
    details for this message) goes after it."""

    stable: str
    dynamic: str = ""

    @property
    def text(self) -> str:
        return f"{self.stable}{self.dynamic}"

    def add(self, text: str) -> None:
        self.dynamic += text


def one_shot_context() -> AIContext:
    """Editor rewrites (shorten, translate…): no user data needed."""
    return AIContext(stable=ONE_SHOT_PROMPT)


async def build_context(
    user_id: str,
    conversation_id: str,
    query: str,
    db: AsyncSession,
    client_time: str | None = None,
    time_zone: str | None = None,
    mode: str = "full",
) -> AIContext:
    """
    Builds the system prompt for the LLM. mode="editor" (the document
    assistant) leaves out tasks, calendar, insights and memories: it works on
    the open document.
    """
    full = mode != "editor"
    now_utc = dt.datetime.now(dt.timezone.utc)
    now_naive = now_utc.replace(tzinfo=None)
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

    # ── Stable part: same text from one message to the next ──
    stable = (
        f"{SYSTEM_PROMPT}\n\n"
        f"--- USER PROFILE ---\n"
        f"- Name: {user_name}\n"
        f"- User Work Days & Hours (from their profile): {describe_work_hours(user_settings)}\n"
        f"- Google Calendar: {'connected' if is_calendar_connected else 'not connected'}\n\n"
    )

    groups_result = await db.execute(
        select(ProjectGroup).filter(ProjectGroup.userId == user_id)
    )
    groups = groups_result.scalars().all()
    if groups:
        stable += "--- EXISTING PROJECT GROUPS (FOLDERS) ---\n"
        for g in groups:
            stable += f"- ID: {g.id}, Name: {g.name}\n"
        stable += "\n"

    ws_result = await db.execute(select(Workspace).filter(Workspace.userId == user_id))
    workspaces = ws_result.scalars().all()
    if workspaces:
        stable += "--- EXISTING WORKSPACES (DOCUMENTS) ---\n"
        for w in workspaces:
            stable += f"- ID: {w.id}, Title: {w.title}, Project Group ID: {w.groupId or 'None (Ungrouped)'}\n"
        stable += "\n"

    tasks: list[Any] = []
    if full:
        tasks_result = await db.execute(
            select(Task)
            .filter(Task.userId == user_id)
            .filter(Task.deletedAt == None)  # noqa: E711
            .order_by(Task.deadline.asc())
        )
        tasks, omitted = select_context_tasks(
            list(tasks_result.scalars().all()), now_naive
        )
        if tasks:
            stable += (
                "--- USER TASKS (INDEX) ---\n"
                "One line per task: ID | title | status | priority | "
                "scheduled start → end | deadline | project | linked document | "
                "subtasks done. Notes and subtasks of the tasks this message is "
                "about are under RELEVANT TASK DETAILS.\n"
            )
            for t in tasks:
                stable += format_task_index(t)
            if omitted:
                stable += f"({omitted} more open tasks not listed)\n"
            stable += "\n"

    # ── Dynamic part: changes with the time or the message ──
    context = AIContext(stable=stable)

    if full and tasks:
        detailed = pick_detailed_tasks(tasks, query, now_naive)
        if detailed:
            context.add("--- RELEVANT TASK DETAILS ---\n")
            for t in detailed:
                context.add(format_task(t))

    if full and is_calendar_connected:
        try:
            items = await get_calendar_items(db, user_id)
            synced_ids = {t.google_event_id for t in tasks if t.google_event_id}
            events_text = format_calendar_events(items, synced_ids, now_utc)
            if events_text:
                context.add(
                    "--- GOOGLE CALENDAR EVENTS (SHOWN IN CALENDAR VIEW) ---\n"
                    + events_text
                )
        except Exception as e:
            logger.warning(f"Calendar events left out of the AI context: {e}")

    if full:
        try:
            context.add(await insights_block(db, user_id))
        except Exception as e:
            logger.warning(f"Insights left out of the AI context: {e}")

        memories = await search_memories(user_id, query, db)
        if memories:
            context.add(f"--- USER MEMORIES ---\n{memories}\n\n")

    conv_result = await db.execute(
        select(Conversation).filter(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if conversation and conversation.summary:
        context.add(
            f"--- PREVIOUS CONVERSATION SUMMARY ---\n{conversation.summary}\n\n"
        )

    context.add(
        f"--- ENVIRONMENT INFO ---\n"
        f"- Current Local Date/Time: {display_time}{tz_info}\n"
        f"- CRITICAL SCHEDULING CONSTRAINT: Every task scheduled for TODAY must have its start and deadline strictly AFTER the current time ({display_time}). You must NEVER schedule tasks in the past.\n"
    )
    return context
