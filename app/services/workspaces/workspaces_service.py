import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models.models import Workspace

class WorkspacesService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, create_input: Dict[str, Any], user_id: str) -> Workspace:
        workspace_id = str(uuid.uuid4())
        
        workspace = Workspace(
            id=workspace_id,
            userId=user_id,
            title=create_input.get("title"),
            emoji=create_input.get("emoji"),
            background_color=create_input.get("background_color"),
            card_show_background=create_input.get("card_show_background"),
            content=create_input.get("content", ""),
            taskId=create_input.get("taskId"),
            folderId=create_input.get("folderId"),
            saveStatus=create_input.get("saveStatus", False)
        )
        
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace

    async def find_all(self, user_id: str, search: Optional[str] = None, folder_id: Optional[str] = None) -> List[Workspace]:
        query = select(Workspace).where(Workspace.userId == user_id)
        if folder_id:
            query = query.where(Workspace.folderId == folder_id)
            
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

    async def update(self, id: str, update_input: Dict[str, Any], user_id: str) -> Workspace:
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

        # Handle taskId/folderId updates (which can be explicitly set to None)
        if "taskId" in update_input:
            workspace.taskId = update_input["taskId"]
        if "folderId" in update_input:
            workspace.folderId = update_input["folderId"]

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

    async def find_by_task_id(self, task_id: str) -> Optional[Workspace]:
        result = await self.db.execute(select(Workspace).where(Workspace.taskId == task_id))
        return result.scalars().first()
