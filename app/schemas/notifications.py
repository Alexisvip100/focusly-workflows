from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from typing import Optional, Any

class NotificationCreateSchema(BaseModel):
    userId: str
    relatedTaskId: Optional[str] = None
    type: Optional[str] = "task_reminder"
    scheduledAt: datetime = Field(default_factory=datetime.utcnow)
    status: Optional[str] = "pending"
    title: Optional[str] = ""
    body: Optional[str] = ""

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            defaults = {
                "type": "task_reminder",
                "status": "pending",
                "title": "",
                "body": ""
            }
            for key, default_val in defaults.items():
                if data.get(key) is None:
                    data[key] = default_val
        return data


    @field_validator("scheduledAt", mode="before")
    @classmethod
    def parse_datetime(cls, val):
        if not val:
            return datetime.utcnow()
        if isinstance(val, datetime):
            return val.replace(tzinfo=None)
        if isinstance(val, str):
            try:
                val = val.replace("Z", "+00:00")
                return datetime.fromisoformat(val).replace(tzinfo=None)
            except:
                return datetime.utcnow()
        return datetime.utcnow()
