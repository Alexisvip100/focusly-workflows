import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models import ProjectGroup, Workspace
from app.modules.workspace.schemas.project_groups import ProjectGroupCreateSchema

class ProjectGroupsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, create_input: Dict[str, Any], user_id: str) -> ProjectGroup:
        group_id = str(uuid.uuid4())
        group_data = ProjectGroupCreateSchema(**create_input)

        group = ProjectGroup(
            id=group_id,
            userId=user_id,
            **group_data.model_dump()
        )

        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def find_all(self, user_id: str) -> List[ProjectGroup]:
        result = await self.db.execute(
            select(ProjectGroup).where(ProjectGroup.userId == user_id).order_by(ProjectGroup.createdAt)
        )
        return list(result.scalars().all())

    async def find_one(self, id: str, user_id: str) -> ProjectGroup:
        result = await self.db.execute(select(ProjectGroup).where(ProjectGroup.id == id))
        group = result.scalars().first()
        if not group or group.userId != user_id:
            raise ValueError(f"ProjectGroup with ID {id} not found")
        return group

    async def update(self, id: str, update_input: Dict[str, Any], user_id: str) -> ProjectGroup:
        result = await self.db.execute(select(ProjectGroup).where(ProjectGroup.id == id))
        group = result.scalars().first()
        if not group or group.userId != user_id:
            raise ValueError(f"ProjectGroup with ID {id} not found")

        if "name" in update_input:
            group.name = update_input["name"]
        if "color" in update_input:
            group.color = update_input["color"]
        if "emoji" in update_input:
            group.emoji = update_input["emoji"]

        group.updatedAt = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def remove(self, id: str, user_id: str) -> bool:
        result = await self.db.execute(select(ProjectGroup).where(ProjectGroup.id == id))
        group = result.scalars().first()
        if not group or group.userId != user_id:
            raise ValueError(f"ProjectGroup with ID {id} not found")



        # Disassociate workspaces from this group
        await self.db.execute(
            update(Workspace).where(Workspace.groupId == id).values(groupId=None, updatedAt=datetime.utcnow())
        )

        await self.db.delete(group)
        await self.db.commit()
        return True

    async def get_total(self, user_id: str) -> int:
        from sqlalchemy import func
        result = await self.db.execute(select(func.count(ProjectGroup.id)).where(ProjectGroup.userId == user_id))
        return result.scalar() or 0
