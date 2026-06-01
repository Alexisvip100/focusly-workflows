import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import FocusSession
from app.schemas.focus_sessions import FocusSessionCreateSchema

class FocusSessionsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, session_data: Dict[str, Any]) -> FocusSession:
        session_id = session_data.get("id") or str(uuid.uuid4())
        parsed_session = FocusSessionCreateSchema(**session_data)
        
        new_session = FocusSession(
            id=session_id,
            **parsed_session.model_dump()
        )
        self.db.add(new_session)
        await self.db.commit()
        await self.db.refresh(new_session)
        return new_session

    async def findAll(self) -> List[FocusSession]:
        result = await self.db.execute(select(FocusSession))
        return list(result.scalars().all())

    async def findOne(self, id: str) -> Optional[FocusSession]:
        result = await self.db.execute(select(FocusSession).where(FocusSession.id == id))
        return result.scalars().first()

    async def findAllByUser(self, user_id: str) -> List[FocusSession]:
        result = await self.db.execute(
            select(FocusSession).where(FocusSession.userId == user_id)
        )
        return list(result.scalars().all())
