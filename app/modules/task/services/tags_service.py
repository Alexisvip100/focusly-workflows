import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag
from app.modules.task.schemas.tags import TagCreateSchema
from app.modules.task.repository import TagsRepository

class TagsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = TagsRepository(db)

    async def create(self, tag_data: dict[str, Any]) -> str:
        tag_id = str(uuid.uuid4())
        parsed_tag = TagCreateSchema(**tag_data)
        
        tag = Tag(
            id=tag_id,
            **parsed_tag.model_dump()
        )
        await self.repository.create(tag)
        return tag_id

    async def find_all(self) -> list[Tag]:
        return await self.repository.get_all()

    async def find_one(self, name: str) -> Tag:
        tag = await self.repository.get_by_id_or_name(name)
        if not tag:
            raise ValueError(f"Tag {name} not found")
        return tag

    async def find_all_by_user(self, user_id: str) -> list[Tag]:
        return await self.repository.get_all_by_user(user_id)
