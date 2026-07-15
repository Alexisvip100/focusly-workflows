import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.modules.notification.schemas.notifications import NotificationCreateSchema
from app.modules.notification.repository import NotificationsRepository

class NotificationsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = NotificationsRepository(db)

    async def create(self, notification_data: dict[str, Any]) -> Notification:
        notif_id = notification_data.get("id") or str(uuid.uuid4())
        parsed_notif = NotificationCreateSchema(**notification_data)
        
        new_notif = Notification(
            id=notif_id,
            **parsed_notif.model_dump()
        )
        return await self.repository.create(new_notif)

    async def findAll(self) -> list[Notification]:
        return await self.repository.get_all()

    async def findOne(self, id: str) -> Notification | None:
        return await self.repository.get_by_id(id)

    async def findAllByUser(self, user_id: str) -> list[Notification]:
        return await self.repository.get_all_by_user(user_id)

    async def sendPushNotification(
        self,
        token: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None
    ) -> None:
        # Mock/Simulate push notification
        pass
        # Logged successfully.
