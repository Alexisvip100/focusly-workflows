from pydantic import BaseModel
from typing import Optional

class ProjectGroupCreateSchema(BaseModel):
    name: str
    color: Optional[str] = None
    emoji: Optional[str] = None
