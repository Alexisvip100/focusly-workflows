import strawberry
from sqlalchemy.future import select
from app.graphql import types
from app.graphql.common import get_user_id
from app.models import Notification

@strawberry.type
class NotificationQuery:
    @strawberry.field
    async def get_notifications(self, info) -> list[types.NotificationType]:
        user_id = get_user_id(info)
        db = info.context["db"]
        
        result = await db.execute(
            select(Notification)
            .where(Notification.userId == user_id)
            .order_by(Notification.createdAt.desc())
        )
        notifications = result.scalars().all()
        return [types.map_model_to_strawberry_notification(n) for n in notifications]
