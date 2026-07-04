import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Tag
from app.modules.task.schemas.tags import TagCreateSchema

class TagsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, tag_data: Dict[str, Any]) -> str:
        tag_id = str(uuid.uuid4())
        parsed_tag = TagCreateSchema(**tag_data)
        
        tag = Tag(
            id=tag_id,
            **parsed_tag.model_dump()
        )
        
        self.db.add(tag)
        await self.db.commit()
        return tag_id

    async def find_all(self) -> List[Tag]:
        result = await self.db.execute(select(Tag))
        return list(result.scalars().all())

    async def find_one(self, name: str) -> Tag:
        # Search by id first, then by name
        result = await self.db.execute(select(Tag).where(Tag.id == name))
        tag = result.scalars().first()
        
        if not tag:
            result = await self.db.execute(select(Tag).where(Tag.name == name))
            tag = result.scalars().first()

        if not tag:
            raise ValueError(f"Tag {name} not found")
        return tag

    async def find_all_by_user(self, user_id: str) -> List[Tag]:
        result = await self.db.execute(select(Tag).where(Tag.userId == user_id))
        return list(result.scalars().all())
