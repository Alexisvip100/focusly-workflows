import strawberry
from app.graphql import types
from app.graphql.common import get_user_id
from app.modules.notification.repository import NotificationsRepository


@strawberry.type
class NotificationMutation:
    @strawberry.mutation
    async def mark_notification_as_read(
        self, info, id: str
    ) -> types.NotificationType | None:
        user_id = get_user_id(info)
        db = info.context["db"]

        repo = NotificationsRepository(db)
        n = await repo.get_by_id(id)
        if n and n.userId == user_id:
            n.status = "read"
            await repo.save(n)
            return types.map_model_to_strawberry_notification(n)
        return None

    @strawberry.mutation
    async def mark_all_notifications_as_read(self, info) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]

        repo = NotificationsRepository(db)
        rowcount = await repo.mark_all_read(user_id)
        return rowcount > 0

    @strawberry.mutation
    async def delete_notification(self, info, id: str) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]

        repo = NotificationsRepository(db)
        rowcount = await repo.delete_by_id_and_user(id, user_id)
        return rowcount > 0

    @strawberry.mutation
    async def delete_all_notifications(self, info) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]

        repo = NotificationsRepository(db)
        await repo.delete_all_by_user(user_id)
        return True
