from typing import Any

from pydantic import BaseModel, model_validator


class TagCreateSchema(BaseModel):
    name: str | None = ""
    userId: str | None = None

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("name") is None:
                data["name"] = ""
        return data
