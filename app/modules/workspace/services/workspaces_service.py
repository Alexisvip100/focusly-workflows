import uuid
import asyncio
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
            **workspace_data.model_dump(),
        )
        return await self.repository.create(workspace)

    async def find_all(
        self,
        user_id: str,
        search: str | None = None,
        group_id: str | None = None,
        limit: int = 24,
        offset: int = 0,
    ) -> dict[str, Any]:
        res = await self.repository.find_all(
            user_id=user_id,
            search=search,
            group_id=group_id,
            limit=limit,
            offset=offset,
        )
        total_workspaces = res["total"]
        return {
            "items": res["items"],
            "total": total_workspaces,
            "page": (offset // limit + 1) if limit > 0 else 1,
            "limit": limit,
            "hasMore": (offset + limit) < total_workspaces,
        }

    async def find_one(self, id: str, user_id: str) -> Workspace:
        workspace = await self.repository.get_by_id_and_user(id, user_id)
        if not workspace:
            raise ValueError(f"Workspace with ID {id} not found")
        return workspace

    async def update(
        self, id: str, update_input: dict[str, Any], user_id: str
    ) -> Workspace:
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
        saved = await self.repository.save(workspace)

        # ── Trigger: Automatización TODO ─────────────────────────────────────
        # Solo se ejecuta si el contenido del workspace cambió.
        # Se lanza como tarea en background para NO bloquear ni ralentizar
        # la respuesta del save. Si falla, no afecta al usuario.
        if "content" in update_input and saved.content:
            from app.modules.automation.services.automation_engine import run_todo_automation
            from app.database import async_session_local

            async def _run_automation_bg():  # noqa: E306
                try:
                    async with async_session_local() as bg_db:
                        await run_todo_automation(
                            workspace_id=saved.id,
                            user_id=user_id,
                            content=saved.content,
                            db=bg_db,
                        )
                except Exception:
                    pass  # El workflow nunca debe romper el save

            asyncio.create_task(_run_automation_bg())
        # ─────────────────────────────────────────────────────────────────────

        return saved

    async def remove(self, id: str, user_id: str) -> bool:
        workspace = await self.repository.get_by_id_and_user(id, user_id)
        if not workspace:
            raise ValueError(f"Workspace with ID {id} not found")

        await self.repository.delete(workspace)
        return True

    async def find_by_task_id(self, task_id: str) -> Workspace | None:
        return await self.repository.get_by_task_id(task_id)
