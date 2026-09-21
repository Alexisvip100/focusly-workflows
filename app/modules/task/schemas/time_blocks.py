from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timezone
from typing import Any


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimeBlockCreateSchema(BaseModel):
    userId: str
    taskId: str | None = None
    startTime: datetime = Field(default_factory=_utcnow_naive)
    endTime: datetime = Field(default_factory=_utcnow_naive)
    blockType: str
    externalEventId: str | None = None
    source: str
    title: str | None = ""
    meetingUrl: str | None = None
    attendees: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            defaults = {"title": "", "attendees": []}
            for key, default_val in defaults.items():
                if data.get(key) is None:
                    data[key] = default_val
        return data

    @field_validator("startTime", "endTime", mode="before")
    @classmethod
    def parse_datetime(cls, val):
        if not val:
            return _utcnow_naive()
        if isinstance(val, datetime):
            return val.replace(tzinfo=None)
        if isinstance(val, str):
            try:
                val = val.replace("Z", "+00:00")
                return datetime.fromisoformat(val).replace(tzinfo=None)
            except:
                return _utcnow_naive()
        return _utcnow_naive()
