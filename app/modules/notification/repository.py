from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete
from app.models import Notification

class NotificationsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification: Notification, commit: bool = True) -> Notification:
        self.db.add(notification)
        if commit:
            await self.db.commit()
            await self.db.refresh(notification)
        else:
            await self.db.flush()
        return notification

    async def get_by_id(self, notification_id: str) -> Notification | None:
        result = await self.db.execute(select(Notification).where(Notification.id == notification_id))
        return result.scalars().first()

    async def get_all(self) -> list[Notification]:
        result = await self.db.execute(select(Notification))
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: str) -> list[Notification]:
        result = await self.db.execute(
            select(Notification)
            .where(Notification.userId == user_id)
            .order_by(Notification.createdAt.desc())
        )
        return list(result.scalars().all())

    async def get_unread_count(self, user_id: str) -> int:
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.userId == user_id,
                Notification.read == False
            )
        )
        return result.scalar() or 0

    async def save(self, notification: Notification) -> Notification:
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def delete(self, notification: Notification) -> None:
        await self.db.delete(notification)
        await self.db.commit()

    async def mark_all_read(self, user_id: str) -> int:
        from sqlalchemy import update
        result = await self.db.execute(
            update(Notification)
            .where(Notification.userId == user_id, Notification.status != "read")
            .values(status="read")
        )
        await self.db.commit()
        return result.rowcount

    async def delete_by_id_and_user(self, notification_id: str, user_id: str) -> int:
        result = await self.db.execute(
            delete(Notification).where(
                Notification.id == notification_id, Notification.userId == user_id
            )
        )
        await self.db.commit()
        return result.rowcount

    async def delete_all_by_user(self, user_id: str) -> None:
        await self.db.execute(
            delete(Notification).where(Notification.userId == user_id)
        )
        await self.db.commit()

    async def update_status_by_id_and_user(self, notification_id: str, user_id: str, status: str) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.userId == user_id
            )
        )
        notification = result.scalars().first()
        if notification:
            notification.status = status
            await self.db.commit()
            await self.db.refresh(notification)
            return notification
        return None
