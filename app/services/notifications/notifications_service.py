import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import Notification
from app.schemas.notifications import NotificationCreateSchema


class NotificationsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification_data: dict[str, Any]) -> Notification:
        notif_id = notification_data.get("id") or str(uuid.uuid4())
        parsed_notif = NotificationCreateSchema(**notification_data)

        new_notif = Notification(id=notif_id, **parsed_notif.model_dump())
        self.db.add(new_notif)
        await self.db.commit()
        await self.db.refresh(new_notif)
        return new_notif

    async def findAll(self) -> list[Notification]:
        result = await self.db.execute(select(Notification))
        return list(result.scalars().all())

    async def findOne(self, id: str) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(Notification.id == id)
        )
        return result.scalars().first()

    async def findAllByUser(self, user_id: str) -> list[Notification]:
        result = await self.db.execute(
            select(Notification).where(Notification.userId == user_id)
        )
        return list(result.scalars().all())

    async def sendPushNotification(
        self, token: str, title: str, body: str, data: dict[str, str] | None = None
    ) -> None:
        # Mock/Simulate push notification
        print(f"[PUSH NOTIFICATION] Sending to token: {token}")
        print(f"Title: {title}")
        print(f"Body: {body}")
        if data:
            print(f"Data: {data}")
        # Logged successfully.
