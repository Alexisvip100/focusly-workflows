from pydantic import BaseModel, model_validator
from typing import Optional, Any

class TagCreateSchema(BaseModel):
    name: Optional[str] = ""
    userId: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("name") is None:
                data["name"] = ""
        return data

