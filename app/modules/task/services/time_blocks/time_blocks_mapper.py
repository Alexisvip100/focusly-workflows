from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import TimeBlock
from app.database import safe_attr


def parse_time_block_dt(val: Any) -> datetime | None:
    """Safely parse a datetime or ISO string to a datetime object."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def time_block_to_dict(tb: TimeBlock) -> dict[str, Any]:
    """Serializes a TimeBlock SQLAlchemy model into a standardized dictionary."""
    start_time = safe_attr(tb, "startTime")
    end_time = safe_attr(tb, "endTime")
    created_at = safe_attr(tb, "createdAt")
    updated_at = safe_attr(tb, "updatedAt")

    return {
        "id": safe_attr(tb, "id"),
        "userId": safe_attr(tb, "userId"),
        "taskId": safe_attr(tb, "taskId"),
        "startTime": start_time.isoformat() if start_time and hasattr(start_time, "isoformat") else None,
        "endTime": end_time.isoformat() if end_time and hasattr(end_time, "isoformat") else None,
        "blockType": safe_attr(tb, "blockType"),
        "externalEventId": safe_attr(tb, "externalEventId"),
        "source": safe_attr(tb, "source"),
        "title": safe_attr(tb, "title"),
        "meetingUrl": safe_attr(tb, "meetingUrl"),
        "attendees": safe_attr(tb, "attendees") or [],
        "createdAt": created_at.isoformat() if created_at and hasattr(created_at, "isoformat") else None,
        "updatedAt": updated_at.isoformat() if updated_at and hasattr(updated_at, "isoformat") else None,
    }
