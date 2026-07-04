import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Notification
from app.modules.notification.schemas.notifications import NotificationCreateSchema

class NotificationsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification_data: Dict[str, Any]) -> Notification:
        notif_id = notification_data.get("id") or str(uuid.uuid4())
        parsed_notif = NotificationCreateSchema(**notification_data)
        
        new_notif = Notification(
            id=notif_id,
            **parsed_notif.model_dump()
        )
        self.db.add(new_notif)
        await self.db.commit()
        await self.db.refresh(new_notif)
        return new_notif

    async def findAll(self) -> List[Notification]:
        result = await self.db.execute(select(Notification))
        return list(result.scalars().all())

    async def findOne(self, id: str) -> Optional[Notification]:
        result = await self.db.execute(select(Notification).where(Notification.id == id))
        return result.scalars().first()

    async def findAllByUser(self, user_id: str) -> List[Notification]:
        result = await self.db.execute(
            select(Notification).where(Notification.userId == user_id)
        )
        return list(result.scalars().all())

    async def sendPushNotification(
        self,
        token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None
    ) -> None:
        # Mock/Simulate push notification
        pass
        # Logged successfully.
