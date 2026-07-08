import strawberry
from sqlalchemy.future import select
from sqlalchemy import update, delete
from app.graphql import types
from app.graphql.common import get_user_id
from app.models import Notification

@strawberry.type
class NotificationMutation:
    @strawberry.mutation
    async def mark_notification_as_read(self, info, id: str) -> types.NotificationType | None:
        user_id = get_user_id(info)
        db = info.context["db"]
        
        result = await db.execute(
            select(Notification).where(
                Notification.id == id,
                Notification.userId == user_id
            )
        )
        n = result.scalars().first()
        if n:
            n.status = "read"
            await db.commit()
            await db.refresh(n)
            return types.map_model_to_strawberry_notification(n)
        return None

    @strawberry.mutation
    async def mark_all_notifications_as_read(self, info) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        
        await db.execute(
            update(Notification)
            .where(
                Notification.userId == user_id,
                Notification.status != "read"
            )
            .values(status="read")
        )
        await db.commit()
        return True

    @strawberry.mutation
    async def delete_notification(self, info, id: str) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        
        await db.execute(
            delete(Notification).where(
                Notification.id == id,
                Notification.userId == user_id
            )
        )
        await db.commit()
        return True

    @strawberry.mutation
    async def delete_all_notifications(self, info) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        
        await db.execute(
            delete(Notification).where(Notification.userId == user_id)
        )
        await db.commit()
        return True
