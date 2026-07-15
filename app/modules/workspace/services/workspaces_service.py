import uuid
from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Workspace
from app.modules.workspace.schemas.workspaces import WorkspaceCreateSchema
from app.modules.workspace.repository import WorkspacesRepository

class WorkspacesService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = WorkspacesRepository(db)

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
        return await self.repository.create(workspace)

    async def find_all(self, user_id: str, search: str | None = None, group_id: str | None = None, limit: int | None = None, offset: int | None = None) -> dict[str, Any]:
        return await self.repository.find_all(
            user_id=user_id,
            search=search,
            group_id=group_id,
            limit=limit,
            offset=offset
        )

    async def find_one(self, id: str, user_id: str) -> Workspace:
        workspace = await self.repository.get_by_id_and_user(id, user_id)
        if not workspace:
            raise ValueError(f"Workspace with ID {id} not found")
        return workspace

    async def get_total_workspaces(self, user_id: str) -> int:
        return await self.repository.get_total_workspaces(user_id)

    async def update(self, id: str, update_input: dict[str, Any], user_id: str) -> Workspace:
        workspace = await self.repository.get_by_id_and_user(id, user_id)
        if not workspace:
            raise ValueError(f"Workspace with ID {id} not found")

        now = datetime.utcnow()

        # Handle exclusive taskId: if this workspace is taking a taskId, other workspaces must release it
        task_id = update_input.get("taskId")
        if task_id:
            await self.repository.release_taskId_for_other_workspaces(task_id, id, now)

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
        return await self.repository.save(workspace)

    async def remove(self, id: str, user_id: str) -> bool:
        workspace = await self.repository.get_by_id_and_user(id, user_id)
        if not workspace:
            raise ValueError(f"Workspace with ID {id} not found")

        await self.repository.delete(workspace)
        return True

    async def find_by_task_id(self, task_id: str) -> Workspace | None:
        return await self.repository.get_by_task_id(task_id)
