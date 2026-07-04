from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from typing import Any

class TaskCreateSchema(BaseModel):
    title: str | None = "Untitled Task"
    notesEncrypted: str | None = ""
    estimateTimer: int | None = None
    realTimer: float | None = None
    duration: datetime | None = None
    priorityLevel: int | None = 2
    category: str | None = None
    color: str | None = None
    estimated_start_date: datetime | None = None
    estimated_end_date: datetime | None = None
    deadline: datetime | None = None
    status: str | None = "Todo"
    completedAt: datetime | None = None
    tags: list[Any] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    links: list[Any] = Field(default_factory=list)
    task_type: str | None = "PlatformTask"
    google_event_id: str | None = None
    source: str | None = "platform"
    sync_status: str | None = "synced"
    collaborators: list[dict[str, Any]] = Field(default_factory=list)
    notified: bool | None = False
    lastMinuteNotified: bool | None = False
    use_ai: bool | None = False
    workspaceId: str | None = None
    is_owner: bool | None = True
    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            defaults = {
                "title": "Untitled Task",
                "notesEncrypted": "",
                "priorityLevel": 2,
                "status": "Todo",
                "task_type": "PlatformTask",
                "source": "platform",
                "sync_status": "synced",
                "notified": False,
                "lastMinuteNotified": False,
                "use_ai": False,
                "tags": [],
                "links": [],
                "collaborators": [],
                "is_owner": True
            }
            for key, default_val in defaults.items():
                if data.get(key) is None:
                    data[key] = default_val
        return data

    # Este validador centraliza y reemplaza tu función parse_dt
    @field_validator("duration", "estimated_start_date", "estimated_end_date", "completedAt", "deadline", mode="before")
    @classmethod
    def parse_datetime(cls, val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val.replace(tzinfo=None)
        if isinstance(val, str):
            try:
                val = val.replace("Z", "+00:00")
                return datetime.fromisoformat(val).replace(tzinfo=None)
            except:
                return None
        return None

