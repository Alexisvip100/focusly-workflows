from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from typing import List, Dict, Any, Optional

class TaskCreateSchema(BaseModel):
    title: Optional[str] = "Untitled Task"
    notesEncrypted: Optional[str] = ""
    estimateTimer: Optional[int] = None
    realTimer: Optional[float] = None
    duration: Optional[datetime] = None
    priorityLevel: Optional[int] = 2
    category: Optional[str] = None
    color: Optional[str] = None
    estimated_start_date: Optional[datetime] = None
    estimated_end_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    status: Optional[str] = "Todo"
    completedAt: Optional[datetime] = None
    tags: List[Any] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    links: List[Any] = Field(default_factory=list)
    task_type: Optional[str] = "PlatformTask"
    google_event_id: Optional[str] = None
    source: Optional[str] = "platform"
    sync_status: Optional[str] = "synced"
    collaborators: List[Dict[str, Any]] = Field(default_factory=list)
    notified: Optional[bool] = False
    lastMinuteNotified: Optional[bool] = False
    use_ai: Optional[bool] = False
    workspaceId: Optional[str] = None
    is_owner: Optional[bool] = True
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

