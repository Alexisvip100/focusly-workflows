import uuid
from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TimeBlock
from app.modules.task.schemas.time_blocks import TimeBlockCreateSchema
from app.modules.task.repository import TimeBlocksRepository

class TimeBlocksService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = TimeBlocksRepository(db)

    def _map_to_dict(self, tb: TimeBlock) -> dict[str, Any]:
        return {
            "id": tb.id,
            "userId": tb.userId,
            "taskId": tb.taskId,
            "startTime": tb.startTime.isoformat() if tb.startTime else None,
            "endTime": tb.endTime.isoformat() if tb.endTime else None,
            "blockType": tb.blockType,
            "externalEventId": tb.externalEventId,
            "source": tb.source,
            "title": tb.title,
            "meetingUrl": tb.meetingUrl,
            "attendees": tb.attendees or [],
            "createdAt": tb.createdAt.isoformat() if tb.createdAt else None,
            "updatedAt": tb.updatedAt.isoformat() if tb.updatedAt else None
        }

    def _parse_dt(self, val: Any) -> datetime | None:
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            try:
                val = val.replace("Z", "+00:00")
                return datetime.fromisoformat(val)
            except:
                return None
        return None

    async def create(self, block_data: dict[str, Any]) -> str:
        block_id = block_data.get("id") or str(uuid.uuid4())
        tb_input = TimeBlockCreateSchema(**block_data)
        
        time_block = TimeBlock(
            id=block_id,
            **tb_input.model_dump()
        )
        await self.repository.create(time_block)
        return block_id

    async def create_many(self, blocks_data: list[dict[str, Any]]) -> None:
        if not blocks_data:
            return
            
        new_blocks = []
        for b in blocks_data:
            block_id = b.get("id") or str(uuid.uuid4())
            tb_input = TimeBlockCreateSchema(**b)
            new_blocks.append(TimeBlock(
                id=block_id,
                **tb_input.model_dump()
            ))
        await self.repository.create_many(new_blocks)

    async def find_all(self) -> list[dict[str, Any]]:
        blocks = await self.repository.get_all()
        return [self._map_to_dict(tb) for tb in blocks]

    async def find_one(self, id: str) -> dict[str, Any]:
        tb = await self.repository.get_by_id(id)
        if not tb:
            raise ValueError(f"Time block with ID {id} not found")
        return self._map_to_dict(tb)

    async def find_all_by_user(self, user_id: str) -> list[dict[str, Any]]:
        blocks = await self.repository.get_all_by_user(user_id)
        return [self._map_to_dict(tb) for tb in blocks]

    async def update(self, id: str, update_data: dict[str, Any]) -> dict[str, Any]:
        tb = await self.repository.get_by_id(id)
        if not tb:
            raise ValueError(f"Time block with ID {id} not found")

        for key, value in update_data.items():
            if key in ["id", "createdAt", "updatedAt"]:
                continue
            if hasattr(tb, key):
                if key in ["startTime", "endTime"]:
                    setattr(tb, key, self._parse_dt(value))
                else:
                    setattr(tb, key, value)

        tb.updatedAt = datetime.utcnow()
        await self.repository.save(tb)
        return self._map_to_dict(tb)

    async def get_synced_google_ids(self, user_id: str) -> list[str]:
        return await self.repository.get_synced_google_ids(user_id)

    async def delete_many_focus_blocks(self, user_id: str) -> None:
        await self.repository.delete_many_focus_blocks(user_id)

    async def delete_many_by_external_ids(self, user_id: str, external_ids: list[str]) -> None:
        await self.repository.delete_many_by_external_ids(user_id, external_ids)
