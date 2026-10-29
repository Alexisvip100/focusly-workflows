import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import transaction_scope
from app.models import Canvas, User
from app.modules.billing.plans import CanvasLimits, PlanLimitError, canvas_limits
from app.modules.canvas.repository import CanvasRepository
from app.modules.canvas.schemas.canvas import CanvasCreateSchema, CanvasUpdateSchema
from app.modules.canvas.services.canvas_files import (
    delete_canvas_files,
    delete_canvas_preview,
    generate_canvas_file_read_url,
    generate_canvas_file_upload_url,
    generate_canvas_preview_upload_url,
    is_canvas_file_id,
)
from app.modules.workspace.repository import WorkspacesRepository


def _scene_bytes(data: Any) -> int:
    # Measured as the schema measures it (its hard cap is Pro's limit)
    return len(json.dumps(data or {}))


def _stored_image_ids(canvas: Canvas) -> set[str]:
    files = (canvas.data or {}).get("files") or {}
    return set(files) if isinstance(files, dict) else set()


class CanvasService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = CanvasRepository(db)

    async def limits(self, user_id: str) -> CanvasLimits:
        """What the user's plan lets their canvases hold."""
        return canvas_limits(await self.db.get(User, user_id))

    def _check_scene_size(
        self, data: Any, limits: CanvasLimits, current: int = 0
    ) -> None:
        # A scene already past the limit (saved under Pro, before a downgrade)
        # can still be saved while it doesn't grow: edits aren't lost.
        size = _scene_bytes(data)
        if size > limits.max_scene_bytes and size > current:
            raise PlanLimitError(
                "canvas_too_large",
                "This canvas is too large for your plan",
                limit=limits.max_scene_bytes,
            )

    async def create(self, create_input: dict[str, Any], user_id: str) -> Canvas:
        canvas_data = CanvasCreateSchema(**create_input)
        limits = await self.limits(user_id)
        if (
            limits.max_canvases is not None
            and await self.repository.count_by_user(user_id) >= limits.max_canvases
        ):
            raise PlanLimitError(
                "canvas_limit_reached",
                f"Your plan includes up to {limits.max_canvases} canvases",
                limit=limits.max_canvases,
            )
        self._check_scene_size(canvas_data.data, limits)
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
                self._check_scene_size(
                    changes["data"],
                    await self.limits(user_id),
                    current=_scene_bytes(canvas.data),
                )
                canvas.data = changes["data"]

            canvas.updatedAt = datetime.now(timezone.utc).replace(tzinfo=None)
            return await self.repository.save(canvas)

    async def remove(self, id: str, user_id: str) -> bool:
        async with transaction_scope(self.db):
            canvas = await self.repository.get_by_id_and_user(id, user_id)
            if not canvas:
                raise ValueError(f"Canvas with ID {id} not found")
            await self.repository.delete(canvas)
        # Its images go too (best effort: storage isn't transactional)
        await asyncio.to_thread(delete_canvas_files, user_id, id)
        return True

    async def create_file_upload(
        self, canvas_id: str, user_id: str, file_id: str, mime_type: str, size: int
    ) -> str:
        """Where to upload one image pasted into one of the user's canvases."""
        canvas = await self.find_one(canvas_id, user_id)
        # Checks the type and the hard size cap first
        upload_url = generate_canvas_file_upload_url(
            user_id, canvas_id, file_id, mime_type, size
        )
        limits = await self.limits(user_id)
        if size > limits.max_image_bytes:
            raise PlanLimitError(
                "canvas_image_too_large",
                "This image is too large for your plan",
                limit=limits.max_image_bytes,
            )
        # Counted from the saved scene; an image already in it (a retried
        # upload) doesn't count again
        stored = _stored_image_ids(canvas)
        if file_id not in stored and len(stored) >= limits.max_images_per_canvas:
            raise PlanLimitError(
                "canvas_image_limit",
                f"A canvas can hold up to {limits.max_images_per_canvas} images on your plan",
                limit=limits.max_images_per_canvas,
            )
        return upload_url

    async def file_urls(self, canvas_id: str, user_id: str) -> list[dict[str, str]]:
        """Signed links to read the images a canvas's saved scene uses."""
        canvas = await self.find_one(canvas_id, user_id)
        files = (canvas.data or {}).get("files") or {}
        if not isinstance(files, dict):
            return []
        return [
            {
                "id": file_id,
                "mimeType": str((meta or {}).get("mimeType") or ""),
                "url": generate_canvas_file_read_url(user_id, canvas_id, file_id),
            }
            for file_id, meta in files.items()
            if is_canvas_file_id(file_id)
        ]

    async def create_preview_upload(
        self, canvas_id: str, user_id: str, mime_type: str, size: int
    ) -> str:
        """Where to upload a new preview of one of the user's canvases. The
        canvas is marked as having it now, so lists hand out a fresh link."""
        async with transaction_scope(self.db):
            canvas = await self.find_one(canvas_id, user_id)
            upload_url = generate_canvas_preview_upload_url(
                user_id, canvas_id, mime_type, size
            )
            canvas.previewAt = datetime.now(timezone.utc).replace(tzinfo=None)
            await self.repository.save(canvas)
        return upload_url

    async def remove_preview(self, canvas_id: str, user_id: str) -> bool:
        """For a drawing left empty: its card goes back to showing the icon."""
        async with transaction_scope(self.db):
            canvas = await self.find_one(canvas_id, user_id)
            if canvas.previewAt is None:
                return True
            canvas.previewAt = None
            await self.repository.save(canvas)
        await asyncio.to_thread(delete_canvas_preview, user_id, canvas_id)
        return True
