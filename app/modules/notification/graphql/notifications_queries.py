import strawberry
from app.graphql import types
from app.graphql.common import get_user_id

@strawberry.type
class NotificationQuery:
    @strawberry.field
    async def get_notifications(self, info) -> list[types.NotificationType]:
        user_id = get_user_id(info)
        db = info.context["db"]
        
        from app.modules.notification.repository import NotificationsRepository
        repo = NotificationsRepository(db)
        notifications = await repo.get_all_by_user(user_id)
        return [types.map_model_to_strawberry_notification(n) for n in notifications]
