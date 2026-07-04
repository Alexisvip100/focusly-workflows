import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

from app.models import TimeBlock
from app.modules.task.schemas.time_blocks import TimeBlockCreateSchema

class TimeBlocksService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _map_to_dict(self, tb: TimeBlock) -> Dict[str, Any]:
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

    def _parse_dt(self, val: Any) -> Optional[datetime]:
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

    async def create(self, block_data: Dict[str, Any]) -> str:
        block_id = block_data.get("id") or str(uuid.uuid4())
        tb_input = TimeBlockCreateSchema(**block_data)
        
        time_block = TimeBlock(
            id=block_id,
            **tb_input.model_dump()
        )
        
        self.db.add(time_block)
        await self.db.commit()
        return block_id

    async def create_many(self, blocks_data: List[Dict[str, Any]]) -> None:
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
            
        self.db.add_all(new_blocks)
        await self.db.commit()

    async def find_all(self) -> List[Dict[str, Any]]:
        result = await self.db.execute(select(TimeBlock))
        return [self._map_to_dict(tb) for tb in result.scalars().all()]

    async def find_one(self, id: str) -> Dict[str, Any]:
        result = await self.db.execute(select(TimeBlock).where(TimeBlock.id == id))
        tb = result.scalars().first()
        if not tb:
            raise ValueError(f"Time block with ID {id} not found")
        return self._map_to_dict(tb)

    async def find_all_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        result = await self.db.execute(select(TimeBlock).where(TimeBlock.userId == user_id))
        return [self._map_to_dict(tb) for tb in result.scalars().all()]

    async def update(self, id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.db.execute(select(TimeBlock).where(TimeBlock.id == id))
        tb = result.scalars().first()
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
        await self.db.commit()
        await self.db.refresh(tb)
        return self._map_to_dict(tb)

    async def get_synced_google_ids(self, user_id: str) -> List[str]:
        result = await self.db.execute(
            select(TimeBlock.externalEventId).where(
                TimeBlock.userId == user_id,
                TimeBlock.source == "Google"
            )
        )
        return [r for r in result.scalars().all() if r]

    async def delete_many_focus_blocks(self, user_id: str) -> None:
        await self.db.execute(
            delete(TimeBlock).where(TimeBlock.userId == user_id, TimeBlock.blockType == "Focus_Block")
        )
        await self.db.commit()

    async def delete_many_by_external_ids(self, user_id: str, external_ids: List[str]) -> None:
        if not external_ids:
            return
        await self.db.execute(
            delete(TimeBlock).where(TimeBlock.userId == user_id, TimeBlock.externalEventId.in_(external_ids))
        )
        await self.db.commit()
