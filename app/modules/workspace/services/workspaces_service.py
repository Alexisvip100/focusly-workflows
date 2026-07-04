import uuid
from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models import Workspace
from app.modules.workspace.schemas.workspaces import WorkspaceCreateSchema

class WorkspacesService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, create_input: dict[str, Any], user_id: str) -> Workspace:
        workspace_id = str(uuid.uuid4())
        group_id = create_input.pop("groupId", None)

        workspace_data = WorkspaceCreateSchema(**create_input)
        
        workspace = Workspace(
            id=workspace_id,
            userId=user_id,
            groupId=group_id,
            **workspace_data.model_dump()
        )
        
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace

    async def find_all(self, user_id: str, search: str | None = None, group_id: str | None = None) -> list[Workspace]:
        query = select(Workspace).where(Workspace.userId == user_id)
        if group_id is not None:
            query = query.where(Workspace.groupId == group_id)
            
        result = await self.db.execute(query)
        workspaces = list(result.scalars().all())
        
        if search:
            search_lower = search.lower()
            workspaces = [
                w for w in workspaces
                if search_lower in (w.title or "").lower() or search_lower in (w.content or "").lower()
            ]
            
        return workspaces

    async def find_one(self, id: str, user_id: str) -> Workspace:
        result = await self.db.execute(select(Workspace).where(Workspace.id == id))
        workspace = result.scalars().first()
        if not workspace or workspace.userId != user_id:
            raise ValueError(f"Workspace with ID {id} not found")
        return workspace

    async def get_total_workspaces(self, user_id: str) -> int:
        from sqlalchemy import func
        result = await self.db.execute(select(func.count(Workspace.id)).where(Workspace.userId == user_id))
        return result.scalar() or 0

    async def update(self, id: str, update_input: dict[str, Any], user_id: str) -> Workspace:
        result = await self.db.execute(select(Workspace).where(Workspace.id == id))
        workspace = result.scalars().first()
        if not workspace or workspace.userId != user_id:
            raise ValueError(f"Workspace with ID {id} not found")

        now = datetime.utcnow()

        # Handle exclusive taskId: if this workspace is taking a taskId, other workspaces must release it
        task_id = update_input.get("taskId")
        if task_id:
            await self.db.execute(
                update(Workspace)
                .where(Workspace.taskId == task_id, Workspace.id != id)
                .values(taskId=None, updatedAt=now)
            )

        if "title" in update_input:
            workspace.title = update_input["title"]
        if "content" in update_input:
            workspace.content = update_input["content"]
        if "saveStatus" in update_input:
            workspace.saveStatus = update_input["saveStatus"]
            
        # Handle emoji removal/persistence
        emoji = update_input.get("emoji")
        if emoji == "" or emoji is None:
            workspace.emoji = None
        else:
            workspace.emoji = emoji
            
        # Handle background color
        bg = update_input.get("background_color")
        if bg == "none" or bg is None:
            workspace.background_color = None
        else:
            workspace.background_color = bg

        if "card_show_background" in update_input:
            workspace.card_show_background = update_input["card_show_background"]

        # Handle taskId updates (which can be explicitly set to None)
        if "taskId" in update_input:
            workspace.taskId = update_input["taskId"]
        if "groupId" in update_input:
            workspace.groupId = update_input["groupId"]

        workspace.updatedAt = now
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace

    async def remove(self, id: str, user_id: str) -> bool:
        result = await self.db.execute(select(Workspace).where(Workspace.id == id))
        workspace = result.scalars().first()
        if not workspace or workspace.userId != user_id:
            raise ValueError(f"Workspace with ID {id} not found")

        await self.db.delete(workspace)
        await self.db.commit()
        return True

    async def find_by_task_id(self, task_id: str) -> Workspace | None:
        result = await self.db.execute(select(Workspace).where(Workspace.taskId == task_id))
        return result.scalars().first()
