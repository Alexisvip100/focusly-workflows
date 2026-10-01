from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import Task
from app.database import safe_attr


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
    duration = safe_attr(t, "duration")
    est_start = safe_attr(t, "estimated_start_date")
    est_end = safe_attr(t, "estimated_end_date")
    deadline = safe_attr(t, "deadline")
    completed_at = safe_attr(t, "completedAt")
    created_at = safe_attr(t, "createdAt")
    updated_at = safe_attr(t, "updatedAt")
    deleted_at = safe_attr(t, "deletedAt")

    return {
        "id": safe_attr(t, "id"),
        "userId": safe_attr(t, "userId"),
        "title": safe_attr(t, "title"),
        "notesEncrypted": safe_attr(t, "notesEncrypted"),
        "estimateTimer": safe_attr(t, "estimateTimer"),
        "realTimer": safe_attr(t, "realTimer"),
        "duration": duration.isoformat() if duration and hasattr(duration, "isoformat") else None,
        "priorityLevel": safe_attr(t, "priorityLevel"),
        "category": safe_attr(t, "category"),
        "color": safe_attr(t, "color"),
        "estimated_start_date": (
            est_start.isoformat() if est_start and hasattr(est_start, "isoformat") else None
        ),
        "estimated_end_date": (
            est_end.isoformat() if est_end and hasattr(est_end, "isoformat") else None
        ),
        "deadline": deadline.isoformat() if deadline and hasattr(deadline, "isoformat") else None,
        "status": safe_attr(t, "status"),
        "completedAt": completed_at.isoformat() if completed_at and hasattr(completed_at, "isoformat") else None,
        "createdAt": created_at.isoformat() if created_at and hasattr(created_at, "isoformat") else None,
        "updatedAt": updated_at.isoformat() if updated_at and hasattr(updated_at, "isoformat") else None,
        "deletedAt": deleted_at.isoformat() if deleted_at and hasattr(deleted_at, "isoformat") else None,
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
