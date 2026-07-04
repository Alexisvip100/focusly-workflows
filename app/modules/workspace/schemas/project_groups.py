from pydantic import BaseModel

class ProjectGroupCreateSchema(BaseModel):
    name: str
    color: str | None = None
    emoji: str | None = None
