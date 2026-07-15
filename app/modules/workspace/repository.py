from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, update, func
from app.models import Workspace, ProjectGroup

class WorkspacesRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, workspace: Workspace) -> Workspace:
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace

    async def get_by_id(self, workspace_id: str) -> Workspace | None:
        result = await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        return result.scalars().first()

    async def get_by_id_and_user(self, workspace_id: str, user_id: str) -> Workspace | None:
        result = await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalars().first()
        if not workspace or workspace.userId != user_id:
            return None
        return workspace

    async def get_by_task_id(self, task_id: str) -> Workspace | None:
        result = await self.db.execute(select(Workspace).where(Workspace.taskId == task_id))
        return result.scalars().first()

    async def get_all_by_user(self, user_id: str) -> list[Workspace]:
        result = await self.db.execute(select(Workspace).where(Workspace.userId == user_id))
        return list(result.scalars().all())

    async def get_total_workspaces(self, user_id: str) -> int:
        result = await self.db.execute(select(func.count(Workspace.id)).where(Workspace.userId == user_id))
        return result.scalar() or 0

    async def find_all(
        self,
        user_id: str,
        search: str | None = None,
        group_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None
    ) -> dict[str, Any]:
        query = select(Workspace).where(Workspace.userId == user_id)
        if group_id is not None:
            if group_id == 'ungrouped':
                query = query.where(Workspace.groupId.is_(None))
            else:
                query = query.where(Workspace.groupId == group_id)
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (Workspace.title.ilike(search_pattern)) | 
                (Workspace.content.ilike(search_pattern))
            )
            
        query = query.order_by(Workspace.updatedAt.desc())
        
        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)
            
        result = await self.db.execute(query)
        total_res = await self.db.execute(select(func.count(Workspace.id)).where(Workspace.userId == user_id))
        total = total_res.scalar() or 0
        return {
            "items": list(result.scalars().all()),
            "total": total
        }

    async def release_taskId_for_other_workspaces(self, task_id: str, exclude_workspace_id: str, now: datetime) -> None:
        await self.db.execute(
            update(Workspace)
            .where(Workspace.taskId == task_id, Workspace.id != exclude_workspace_id)
            .values(taskId=None, updatedAt=now)
        )

    async def save(self, workspace: Workspace) -> Workspace:
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace

    async def delete(self, workspace: Workspace) -> None:
        await self.db.delete(workspace)
        await self.db.commit()


class ProjectGroupsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, group: ProjectGroup) -> ProjectGroup:
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def get_by_id(self, group_id: str) -> ProjectGroup | None:
        result = await self.db.execute(select(ProjectGroup).where(ProjectGroup.id == group_id))
        return result.scalars().first()

    async def get_by_id_and_user(self, group_id: str, user_id: str) -> ProjectGroup | None:
        result = await self.db.execute(select(ProjectGroup).where(ProjectGroup.id == group_id))
        group = result.scalars().first()
        if not group or group.userId != user_id:
            return None
        return group

    async def get_all_by_user(self, user_id: str) -> list[ProjectGroup]:
        result = await self.db.execute(
            select(ProjectGroup).where(ProjectGroup.userId == user_id).order_by(ProjectGroup.createdAt)
        )
        return list(result.scalars().all())

    async def get_total(self, user_id: str) -> int:
        result = await self.db.execute(select(func.count(ProjectGroup.id)).where(ProjectGroup.userId == user_id))
        return result.scalar() or 0

    async def delete_workspaces_by_group_id(self, group_id: str) -> None:
        await self.db.execute(
            delete(Workspace).where(Workspace.groupId == group_id)
        )

    async def save(self, group: ProjectGroup) -> ProjectGroup:
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def delete(self, group: ProjectGroup) -> None:
        await self.db.delete(group)
        await self.db.commit()
