from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from typing import List, Dict, Any, Optional

class TimeBlockCreateSchema(BaseModel):
    userId: str
    taskId: Optional[str] = None
    startTime: datetime = Field(default_factory=datetime.utcnow)
    endTime: datetime = Field(default_factory=datetime.utcnow)
    blockType: str
    externalEventId: Optional[str] = None
    source: str
    title: Optional[str] = ""
    meetingUrl: Optional[str] = None
    attendees: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            defaults = {
                "title": "",
                "attendees": []
            }
            for key, default_val in defaults.items():
                if data.get(key) is None:
                    data[key] = default_val
        return data

    @field_validator("startTime", "endTime", mode="before")
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

