from pydantic import BaseModel
from typing import Optional

class FolderCreateSchema(BaseModel):
    name: str
    color: Optional[str] = None
