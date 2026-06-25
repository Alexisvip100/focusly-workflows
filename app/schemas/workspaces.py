from typing import Any

from pydantic import BaseModel, model_validator


class WorkspaceCreateSchema(BaseModel):
    title: str | None = None
    emoji: str | None = None
    background_color: str | None = None
    card_show_background: bool | None = None
    content: str | None = ""
    taskId: str | None = None
    folderId: str | None = None
    saveStatus: bool | None = False

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            defaults = {"content": "", "saveStatus": False}
            for key, default_val in defaults.items():
                if data.get(key) is None:
                    data[key] = default_val
        return data
