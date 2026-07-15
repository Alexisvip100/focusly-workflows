import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProjectGroup
from app.modules.workspace.schemas.project_groups import ProjectGroupCreateSchema
from app.modules.workspace.repository import ProjectGroupsRepository

class ProjectGroupsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = ProjectGroupsRepository(db)

    async def create(self, create_input: dict[str, Any], user_id: str) -> ProjectGroup:
        group_id = str(uuid.uuid4())
        group_data = ProjectGroupCreateSchema(**create_input)

        group = ProjectGroup(
            id=group_id,
            userId=user_id,
            **group_data.model_dump()
        )
        return await self.repository.create(group)

    async def find_all(self, user_id: str) -> list[ProjectGroup]:
        return await self.repository.get_all_by_user(user_id)

    async def find_one(self, id: str, user_id: str) -> ProjectGroup:
        group = await self.repository.get_by_id_and_user(id, user_id)
        if not group:
            raise ValueError(f"ProjectGroup with ID {id} not found")
        return group

    async def update(self, id: str, update_input: dict[str, Any], user_id: str) -> ProjectGroup:
        group = await self.repository.get_by_id_and_user(id, user_id)
        if not group:
            raise ValueError(f"ProjectGroup with ID {id} not found")

        if "name" in update_input:
            group.name = update_input["name"]
        if "color" in update_input:
            group.color = update_input["color"]
        if "emoji" in update_input:
            group.emoji = update_input["emoji"]

        group.updatedAt = datetime.utcnow()
        return await self.repository.save(group)

    async def remove(self, id: str, user_id: str) -> bool:
        group = await self.repository.get_by_id_and_user(id, user_id)
        if not group:
            raise ValueError(f"ProjectGroup with ID {id} not found")

        # Delete workspaces belonging to this group
        await self.repository.delete_workspaces_by_group_id(id)
        await self.repository.delete(group)
        return True

    async def get_total(self, user_id: str) -> int:
        return await self.repository.get_total(user_id)
