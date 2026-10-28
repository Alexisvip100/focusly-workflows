from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Canvas


def serialize_canvas(c: Canvas, include_data: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": c.id,
        "userId": c.userId,
        "workspaceId": c.workspaceId,
        "name": c.name,
        "createdAt": c.createdAt.isoformat() if c.createdAt else None,
        "updatedAt": c.updatedAt.isoformat() if c.updatedAt else None,
    }
    if include_data:
        out["data"] = c.data
    return out


class CanvasRepository:
    """Not cached in Redis, unlike workspaces: a canvas is rewritten on every
    autosave, so a cached copy would be invalidated almost as often as read."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, canvas: Canvas, commit: bool = False) -> Canvas:
        self.db.add(canvas)
        if commit:
            await self.db.commit()
            await self.db.refresh(canvas)
        else:
            await self.db.flush()
        return canvas

    async def get_by_id(self, canvas_id: str) -> Canvas | None:
        result = await self.db.execute(select(Canvas).where(Canvas.id == canvas_id))
        return result.scalars().first()

    async def get_by_id_and_user(self, canvas_id: str, user_id: str) -> Canvas | None:
        canvas = await self.get_by_id(canvas_id)
        if not canvas or canvas.userId != user_id:
            return None
        return canvas

    async def get_all_by_workspace(
        self, workspace_id: str, user_id: str
    ) -> list[Canvas]:
        result = await self.db.execute(
            select(Canvas)
            .where(Canvas.workspaceId == workspace_id, Canvas.userId == user_id)
            .order_by(Canvas.updatedAt.desc(), Canvas.id.desc())
        )
        return list(result.scalars().all())

    async def save(self, canvas: Canvas, commit: bool = False) -> Canvas:
        if canvas not in self.db:
            canvas = await self.db.merge(canvas)
        if commit:
            await self.db.commit()
            await self.db.refresh(canvas)
        else:
            await self.db.flush()
        return canvas

    async def delete(self, canvas: Canvas, commit: bool = False) -> None:
        if canvas not in self.db:
            canvas = await self.db.merge(canvas)
        await self.db.delete(canvas)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def delete_by_workspace_ids(self, workspace_ids: list[str]) -> None:
        """Deletes the canvases of these documents. Defers database commit to the caller."""
        if not workspace_ids:
            return
        await self.db.execute(
            delete(Canvas).where(Canvas.workspaceId.in_(workspace_ids))
        )
        await self.db.flush()
