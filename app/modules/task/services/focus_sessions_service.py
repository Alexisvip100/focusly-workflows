import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FocusSession
from app.modules.task.schemas.focus_sessions import FocusSessionCreateSchema
from app.modules.task.repository import FocusSessionsRepository

class FocusSessionsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = FocusSessionsRepository(db)

    async def create(self, session_data: dict[str, Any]) -> FocusSession:
        session_id = session_data.get("id") or str(uuid.uuid4())
        parsed_session = FocusSessionCreateSchema(**session_data)
        
        new_session = FocusSession(
            id=session_id,
            **parsed_session.model_dump()
        )
        return await self.repository.create(new_session)

    async def findAll(self) -> list[FocusSession]:
        return await self.repository.get_all()

    async def findOne(self, id: str) -> FocusSession | None:
        return await self.repository.get_by_id(id)

    async def findAllByUser(self, user_id: str) -> list[FocusSession]:
        return await self.repository.get_all_by_user(user_id)
