import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import transaction_scope
from app.models import Canvas
from app.modules.canvas.repository import CanvasRepository
from app.modules.canvas.schemas.canvas import CanvasCreateSchema, CanvasUpdateSchema
from app.modules.workspace.repository import WorkspacesRepository


class CanvasService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = CanvasRepository(db)

    async def create(self, create_input: dict[str, Any], user_id: str) -> Canvas:
        canvas_data = CanvasCreateSchema(**create_input)
        if canvas_data.workspaceId:
            workspace = await WorkspacesRepository(self.db).get_by_id_and_user(
                canvas_data.workspaceId, user_id
            )
            if not workspace:
                raise ValueError(
                    f"Workspace with ID {canvas_data.workspaceId} not found"
                )

        canvas = Canvas(
            id=str(uuid.uuid4()), userId=user_id, **canvas_data.model_dump()
        )
        async with transaction_scope(self.db):
            return await self.repository.create(canvas)

    async def find_one(self, id: str, user_id: str) -> Canvas:
        canvas = await self.repository.get_by_id_and_user(id, user_id)
        if not canvas:
            raise ValueError(f"Canvas with ID {id} not found")
        return canvas

    async def find_by_workspace(self, workspace_id: str, user_id: str) -> list[Canvas]:
        return await self.repository.get_all_by_workspace(workspace_id, user_id)

    async def update(
        self, id: str, update_input: dict[str, Any], user_id: str
    ) -> Canvas:
        changes = CanvasUpdateSchema(**update_input).model_dump(exclude_unset=True)
        async with transaction_scope(self.db):
            canvas = await self.repository.get_by_id_and_user(id, user_id)
            if not canvas:
                raise ValueError(f"Canvas with ID {id} not found")

            if changes.get("name") is not None:
                canvas.name = changes["name"]
            if changes.get("icon") is not None:
                canvas.icon = changes["icon"]
            if changes.get("data") is not None:
                canvas.data = changes["data"]

            canvas.updatedAt = datetime.now(timezone.utc).replace(tzinfo=None)
            return await self.repository.save(canvas)

    async def remove(self, id: str, user_id: str) -> bool:
        async with transaction_scope(self.db):
            canvas = await self.repository.get_by_id_and_user(id, user_id)
            if not canvas:
                raise ValueError(f"Canvas with ID {id} not found")
            await self.repository.delete(canvas)
            return True
