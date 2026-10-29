import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.modules.billing.plans import PRO_CANVAS_LIMITS

# A scene is saved whole on every autosave; this caps one at a size no hand-drawn
# canvas reaches, so an embedded image or a runaway client can't bloat the table.
# The largest plan's limit; the service holds each user to their own plan's.
MAX_CANVAS_DATA_BYTES = PRO_CANVAS_LIMITS.max_scene_bytes
# One emoji; joined ones (families, flags with modifiers) run to ~10 code points.
MAX_ICON_LENGTH = 32


def _empty_scene() -> dict[str, Any]:
    return {"elements": [], "appState": {}}


def _check_scene(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data.get("elements", []), list):
        raise ValueError("data.elements must be a list")
    if len(json.dumps(data)) > MAX_CANVAS_DATA_BYTES:
        raise ValueError("Canvas data is too large")
    return data


class CanvasCreateSchema(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    icon: str | None = Field(default=None, min_length=1, max_length=MAX_ICON_LENGTH)
    workspaceId: str | None = None
    data: dict[str, Any] = Field(default_factory=_empty_scene)

    @field_validator("data")
    @classmethod
    def validate_data(cls, data: dict[str, Any]) -> dict[str, Any]:
        return _check_scene(data)


class CanvasUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    icon: str | None = Field(default=None, min_length=1, max_length=MAX_ICON_LENGTH)
    data: dict[str, Any] | None = None

    @field_validator("data")
    @classmethod
    def validate_data(cls, data: dict[str, Any] | None) -> dict[str, Any] | None:
        return _check_scene(data) if data is not None else None
