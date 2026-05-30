import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import Notification

class NotificationsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification_data: Dict[str, Any]) -> Notification:
        notif_id = notification_data.get("id") or str(uuid.uuid4())
        
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

        new_notif = Notification(
            id=notif_id,
            userId=notification_data.get("userId"),
            relatedTaskId=notification_data.get("relatedTaskId"),
            type=notification_data.get("type", "task_reminder"),
            scheduledAt=parse_dt(notification_data.get("scheduledAt")),
            status=notification_data.get("status", "pending"),
            title=notification_data.get("title", ""),
            body=notification_data.get("body", "")
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
        # Mock/Simulate push notification without Firebase Admin SDK
        print(f"[PUSH NOTIFICATION] Sending to token: {token}")
        print(f"Title: {title}")
        print(f"Body: {body}")
        if data:
            print(f"Data: {data}")
        # Logged successfully.
