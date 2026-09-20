from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timezone
from typing import Any


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FocusSessionCreateSchema(BaseModel):
    userId: str
    taskId: str
    startedAt: datetime = Field(default_factory=_utcnow_naive)
    endedAt: datetime = Field(default_factory=_utcnow_naive)
    durationMinutes: int | None = 0
    distractionCount: int | None = 0
    wasSuccessful: bool | None = True

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            defaults = {
                "durationMinutes": 0,
                "distractionCount": 0,
                "wasSuccessful": True,
            }
            for key, default_val in defaults.items():
                if data.get(key) is None:
                    data[key] = default_val
        return data

    @field_validator("startedAt", "endedAt", mode="before")
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
