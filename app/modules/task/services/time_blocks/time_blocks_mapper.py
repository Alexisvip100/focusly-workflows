from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import TimeBlock


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
    return {
        "id": tb.id,
        "userId": tb.userId,
        "taskId": tb.taskId,
        "startTime": tb.startTime.isoformat() if tb.startTime else None,
        "endTime": tb.endTime.isoformat() if tb.endTime else None,
        "blockType": tb.blockType,
        "externalEventId": tb.externalEventId,
        "source": tb.source,
        "title": tb.title,
        "meetingUrl": tb.meetingUrl,
        "attendees": tb.attendees or [],
        "createdAt": tb.createdAt.isoformat() if tb.createdAt else None,
        "updatedAt": tb.updatedAt.isoformat() if tb.updatedAt else None,
    }
