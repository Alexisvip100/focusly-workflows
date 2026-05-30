import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import FocusSession

class FocusSessionsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, session_data: Dict[str, Any]) -> FocusSession:
        session_id = session_data.get("id") or str(uuid.uuid4())
        
        def parse_dt(val):
            if not val:
                return datetime.utcnow()
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    val = val.replace("Z", "+00:00")
                    return datetime.fromisoformat(val)
                except:
                    return datetime.utcnow()
            return datetime.utcnow()

        new_session = FocusSession(
            id=session_id,
            userId=session_data.get("userId"),
            taskId=session_data.get("taskId"),
            startedAt=parse_dt(session_data.get("startedAt")),
            endedAt=parse_dt(session_data.get("endedAt")),
            durationMinutes=int(session_data.get("durationMinutes") or 0),
            distractionCount=int(session_data.get("distractionCount") or 0),
            wasSuccessful=bool(session_data.get("wasSuccessful", True))
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
