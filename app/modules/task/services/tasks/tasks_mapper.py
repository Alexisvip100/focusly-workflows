from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import Task


def parse_naive_dt(val: Any) -> datetime | None:
    """Safely parse a datetime or ISO string to a naive UTC datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    if isinstance(val, str):
        try:
            val_clean = val.replace("Z", "+00:00")
            return datetime.fromisoformat(val_clean).replace(tzinfo=None)
        except Exception:
            return None
    return None


def task_to_dict(t: Task) -> dict[str, Any]:
    """Serializes a Task SQLAlchemy model into a standardized dictionary."""
    return {
        "id": t.id,
        "userId": t.userId,
        "title": t.title,
        "notesEncrypted": t.notesEncrypted,
        "estimateTimer": t.estimateTimer,
        "realTimer": t.realTimer,
        "duration": t.duration.isoformat() if t.duration else None,
        "priorityLevel": t.priorityLevel,
        "category": t.category,
        "color": t.color,
        "estimated_start_date": (
            t.estimated_start_date.isoformat() if t.estimated_start_date else None
        ),
        "estimated_end_date": (
            t.estimated_end_date.isoformat() if t.estimated_end_date else None
        ),
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "status": t.status,
        "completedAt": t.completedAt.isoformat() if t.completedAt else None,
        "createdAt": t.createdAt.isoformat() if t.createdAt else None,
        "updatedAt": t.updatedAt.isoformat() if t.updatedAt else None,
        "deletedAt": t.deletedAt.isoformat() if t.deletedAt else None,
        "tags": t.tags or [],
        "filters": t.filters or {},
        "links": t.links or [],
        "task_type": t.task_type or "PlatformTask",
        "google_event_id": t.google_event_id,
        "source": t.source or "platform",
        "sync_status": t.sync_status or "synced",
        "collaborators": getattr(t, "collaborators", None) or [],
        "time_logs": getattr(t, "time_logs", None) or [],
        "subtasks": getattr(t, "subtasks", None) or [],
        "is_owner": getattr(t, "is_owner", True),
        "notified": t.notified or False,
        "lastMinuteNotified": t.lastMinuteNotified or False,
        "use_ai": t.use_ai or False,
        "workspaceId": t.workspaceId,
        "projectId": getattr(t, "projectId", None),
    }


def map_task_to_google_event(task: dict[str, Any]) -> dict[str, Any]:
    """Maps a task dictionary to Google Calendar event body format."""
    deadline_str = task.get("deadline")
    deadline = parse_naive_dt(deadline_str) or datetime.now(timezone.utc).replace(tzinfo=None)

    start = parse_naive_dt(task.get("estimated_start_date")) or deadline

    end = parse_naive_dt(task.get("estimated_end_date"))
    if not end:
        end = start + timedelta(minutes=(task.get("estimateTimer") or 30))

    clean_desc = task.get("notesEncrypted") or ""
    clean_desc = re.sub(r"\[COLOR:(.*?)\]", "", clean_desc)
    clean_desc = re.sub(r"\[START_DATE:(.*?)\]", "", clean_desc).strip()

    collaborators = task.get("collaborators") or []

    return {
        "summary": task.get("title", "Untitled Focusly Task"),
        "description": clean_desc,
        "start": {"dateTime": start.isoformat() + "Z"},
        "end": {"dateTime": end.isoformat() + "Z"},
        "attendees": [
            {"email": c["email"], "displayName": c.get("name", "")}
            for c in collaborators
            if c.get("email")
        ],
    }
