from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete
from app.models import Notification


class NotificationsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self, notification: Notification, commit: bool = False
    ) -> Notification:
        self.db.add(notification)
        if commit:
            await self.db.commit()
            await self.db.refresh(notification)
        else:
            await self.db.flush()
        return notification

    async def get_by_id(self, notification_id: str) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
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
                Notification.userId == user_id, Notification.read == False
            )
        )
        return result.scalar() or 0

    async def save(
        self, notification: Notification, commit: bool = False
    ) -> Notification:
        if notification not in self.db:
            notification = await self.db.merge(notification)
        if commit:
            await self.db.commit()
            await self.db.refresh(notification)
        else:
            await self.db.flush()
        return notification

    async def delete(self, notification: Notification, commit: bool = False) -> None:
        if notification not in self.db:
            notification = await self.db.merge(notification)
        await self.db.delete(notification)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def mark_all_read(self, user_id: str, commit: bool = False) -> int:
        from sqlalchemy import update

        result = await self.db.execute(
            update(Notification)
            .where(Notification.userId == user_id, Notification.status != "read")
            .values(status="read")
        )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return result.rowcount

    async def delete_by_id_and_user(
        self, notification_id: str, user_id: str, commit: bool = False
    ) -> int:
        result = await self.db.execute(
            delete(Notification).where(
                Notification.id == notification_id, Notification.userId == user_id
            )
        )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return result.rowcount

    async def delete_all_by_user(self, user_id: str, commit: bool = False) -> None:
        await self.db.execute(
            delete(Notification).where(Notification.userId == user_id)
        )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def update_status_by_id_and_user(
        self, notification_id: str, user_id: str, status: str, commit: bool = False
    ) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.userId == user_id
            )
        )
        notification = result.scalars().first()
        if notification:
            notification.status = status
            if commit:
                await self.db.commit()
                await self.db.refresh(notification)
            else:
                await self.db.flush()
            return notification
        return None
