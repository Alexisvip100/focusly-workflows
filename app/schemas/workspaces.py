from pydantic import BaseModel, model_validator
from typing import Optional, Any

class WorkspaceCreateSchema(BaseModel):
    title: Optional[str] = None
    emoji: Optional[str] = None
    background_color: Optional[str] = None
    card_show_background: Optional[bool] = None
    content: Optional[str] = ""
    taskId: Optional[str] = None
    folderId: Optional[str] = None
    saveStatus: Optional[bool] = False

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            defaults = {
                "content": "",
                "saveStatus": False
            }
            for key, default_val in defaults.items():
                if data.get(key) is None:
                    data[key] = default_val
        return data

