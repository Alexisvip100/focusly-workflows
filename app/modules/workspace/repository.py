from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, update, func
from app.models import Workspace, ProjectGroup
from app.redis import cache

def serialize_workspace(w: Workspace) -> dict:
    return {
        "id": w.id,
        "userId": w.userId,
        "groupId": w.groupId,
        "taskId": w.taskId,
        "title": w.title,
        "content": w.content,
        "emoji": w.emoji,
        "background_color": w.background_color,
        "card_show_background": w.card_show_background,
        "saveStatus": w.saveStatus,
        "createdAt": w.createdAt.isoformat() if w.createdAt else None,
        "updatedAt": w.updatedAt.isoformat() if w.updatedAt else None
    }

def deserialize_workspace(data: dict) -> Workspace:
    created_at = datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else None
    updated_at = datetime.fromisoformat(data["updatedAt"]) if data.get("updatedAt") else None
    w = Workspace(
        id=data["id"],
        userId=data["userId"],
        groupId=data["groupId"],
        taskId=data["taskId"],
        title=data["title"],
        content=data["content"]
    )
    w.emoji = data.get("emoji")
    w.background_color = data.get("background_color")
    w.card_show_background = data.get("card_show_background")
    w.saveStatus = data.get("saveStatus")
    w.createdAt = created_at
    w.updatedAt = updated_at
    return w

def serialize_group(g: ProjectGroup) -> dict:
    return {
        "id": g.id,
        "userId": g.userId,
        "name": g.name,
        "description": g.description,
        "createdAt": g.createdAt.isoformat() if g.createdAt else None,
        "updatedAt": g.updatedAt.isoformat() if g.updatedAt else None
    }

def deserialize_group(data: dict) -> ProjectGroup:
    created_at = datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else None
    updated_at = datetime.fromisoformat(data["updatedAt"]) if data.get("updatedAt") else None
    g = ProjectGroup(
        id=data["id"],
        userId=data["userId"],
        name=data["name"],
        description=data["description"]
    )
    g.createdAt = created_at
    g.updatedAt = updated_at
    return g

class WorkspacesRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, workspace: Workspace) -> Workspace:
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)
        await cache.set(f"workspace:id:{workspace.id}", serialize_workspace(workspace))
        await cache.delete(f"workspaces:user:{workspace.userId}")
        await cache.delete(f"signals:user:{workspace.userId}")
        return workspace

    async def get_by_id(self, workspace_id: str) -> Workspace | None:
        cached = await cache.get(f"workspace:id:{workspace_id}")
        if cached:
            return deserialize_workspace(cached)
        result = await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalars().first()
        if workspace:
            await cache.set(f"workspace:id:{workspace.id}", serialize_workspace(workspace))
        return workspace

    async def get_by_id_and_user(self, workspace_id: str, user_id: str) -> Workspace | None:
        workspace = await self.get_by_id(workspace_id)
        if not workspace or workspace.userId != user_id:
            return None
        return workspace

    async def get_by_task_id(self, task_id: str) -> Workspace | None:
        result = await self.db.execute(select(Workspace).where(Workspace.taskId == task_id))
        return result.scalars().first()

    async def get_all_by_user(self, user_id: str) -> list[Workspace]:
        cached = await cache.get(f"workspaces:user:{user_id}")
        if cached is not None:
            return [deserialize_workspace(w) for w in cached]
        result = await self.db.execute(select(Workspace).where(Workspace.userId == user_id))
        workspaces = list(result.scalars().all())
        await cache.set(f"workspaces:user:{user_id}", [serialize_workspace(w) for w in workspaces])
        return workspaces

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
        count_query = select(func.count(Workspace.id)).where(Workspace.userId == user_id)
        if group_id is not None:
            if group_id == 'ungrouped':
                query = query.where(Workspace.groupId.is_(None))
                count_query = count_query.where(Workspace.groupId.is_(None))
            else:
                query = query.where(Workspace.groupId == group_id)
                count_query = count_query.where(Workspace.groupId == group_id)
        if search:
            search_pattern = f"%{search}%"
            filter_cond = (Workspace.title.ilike(search_pattern)) | (Workspace.content.ilike(search_pattern))
            query = query.where(filter_cond)
            count_query = count_query.where(filter_cond)
            
        query = query.order_by(Workspace.updatedAt.desc())
        
        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)
            
        result = await self.db.execute(query)
        total_res = await self.db.execute(count_query)
        total = total_res.scalar() or 0
        return {
            "items": list(result.scalars().all()),
            "total": total
        }

    async def release_taskId_for_other_workspaces(self, task_id: str, exclude_workspace_id: str, now: datetime) -> None:
        """Releases taskId from other workspaces. Defers database commit to the caller."""
        await self.db.execute(
            update(Workspace)
            .where(Workspace.taskId == task_id, Workspace.id != exclude_workspace_id)
            .values(taskId=None, updatedAt=now)
        )
        await self.db.flush()
        await cache.delete_pattern("workspaces:user:*")
        await cache.delete_pattern("workspace:id:*")
        await cache.delete_pattern("signals:user:*")

    async def save(self, workspace: Workspace, commit: bool = True) -> Workspace:
        if workspace not in self.db:
            workspace = await self.db.merge(workspace)
        if commit:
            await self.db.commit()
            await self.db.refresh(workspace)
        else:
            await self.db.flush()
        await cache.set(f"workspace:id:{workspace.id}", serialize_workspace(workspace))
        await cache.delete(f"workspaces:user:{workspace.userId}")
        await cache.delete(f"signals:user:{workspace.userId}")
        return workspace

    async def delete(self, workspace: Workspace) -> None:
        if workspace not in self.db:
            workspace = await self.db.merge(workspace)
        await self.db.delete(workspace)
        await self.db.commit()
        await cache.delete(f"workspace:id:{workspace.id}")
        await cache.delete(f"workspaces:user:{workspace.userId}")
        await cache.delete(f"signals:user:{workspace.userId}")


class ProjectGroupsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, group: ProjectGroup) -> ProjectGroup:
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        await cache.set(f"project_group:id:{group.id}", serialize_group(group))
        await cache.delete(f"project_groups:user:{group.userId}")
        return group

    async def get_by_id(self, group_id: str) -> ProjectGroup | None:
        cached = await cache.get(f"project_group:id:{group_id}")
        if cached:
            return deserialize_group(cached)
        result = await self.db.execute(select(ProjectGroup).where(ProjectGroup.id == group_id))
        group = result.scalars().first()
        if group:
            await cache.set(f"project_group:id:{group.id}", serialize_group(group))
        return group

    async def get_by_id_and_user(self, group_id: str, user_id: str) -> ProjectGroup | None:
        group = await self.get_by_id(group_id)
        if not group or group.userId != user_id:
            return None
        return group

    async def get_all_by_user(self, user_id: str) -> list[ProjectGroup]:
        cached = await cache.get(f"project_groups:user:{user_id}")
        if cached is not None:
            return [deserialize_group(g) for g in cached]
        result = await self.db.execute(
            select(ProjectGroup).where(ProjectGroup.userId == user_id).order_by(ProjectGroup.createdAt)
        )
        groups = list(result.scalars().all())
        await cache.set(f"project_groups:user:{user_id}", [serialize_group(g) for g in groups])
        return groups

    async def get_total(self, user_id: str) -> int:
        result = await self.db.execute(select(func.count(ProjectGroup.id)).where(ProjectGroup.userId == user_id))
        return result.scalar() or 0

    async def delete_workspaces_by_group_id(self, group_id: str) -> None:
        """Deletes all workspaces belonging to a group. Defers database commit to the caller."""
        await self.db.execute(
            delete(Workspace).where(Workspace.groupId == group_id)
        )
        await self.db.flush()
        await cache.delete_pattern("workspaces:user:*")
        await cache.delete_pattern("workspace:id:*")

    async def save(self, group: ProjectGroup) -> ProjectGroup:
        if group not in self.db:
            group = await self.db.merge(group)
        await self.db.commit()
        await self.db.refresh(group)
        await cache.set(f"project_group:id:{group.id}", serialize_group(group))
        await cache.delete(f"project_groups:user:{group.userId}")
        return group

    async def delete(self, group: ProjectGroup) -> None:
        if group not in self.db:
            group = await self.db.merge(group)
        await self.db.delete(group)
        await self.db.commit()
        await cache.delete(f"project_group:id:{group.id}")
        await cache.delete(f"project_groups:user:{group.userId}")
