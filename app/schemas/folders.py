from pydantic import BaseModel


class FolderCreateSchema(BaseModel):
    name: str
    color: str | None = None
