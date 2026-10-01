import logging

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import safe_attr, transaction_scope
from app.models import (
    AutomationLog,
    Conversation,
    FocusSession,
    Message,
    Notification,
    ProjectGroup,
    Tag,
    Task,
    TimeBlock,
    User,
    UserMemory,
    Workspace,
)
from app.modules.user.repository import UsersRepository
from app.redis import cache

logger = logging.getLogger(__name__)

# Every table holding a user's data, keyed by its userId column. Message rows
# have no userId and are removed through their conversation.
USER_OWNED_MODELS = (
    UserMemory,
    Conversation,
    AutomationLog,
    Notification,
    FocusSession,
    TimeBlock,
    Tag,
    Task,
    Workspace,
    ProjectGroup,
)


class AccountDeletionService:
    """Permanently deletes a user and everything that belongs to them, as
    promised in the Privacy Notice ("Cancelación")."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def delete_account(self, user: User) -> None:
        user_id = str(safe_attr(user, "id"))

        # External cleanup first, while the Google credentials still exist.
        # All best-effort: a provider being down must not block the deletion.
        await self._stop_calendar_sync(user_id)
        await self._revoke_google_token(safe_attr(user, "googleRefreshToken"))
        self._delete_avatars(user_id)

        task_ids = await self._ids(Task.id, Task.userId == user_id)
        workspace_ids = await self._ids(Workspace.id, Workspace.userId == user_id)
        group_ids = await self._ids(ProjectGroup.id, ProjectGroup.userId == user_id)
        conversation_ids = await self._ids(
            Conversation.id, Conversation.userId == user_id
        )

        async with transaction_scope(self.db):
            if conversation_ids:
                await self.db.execute(
                    delete(Message).where(Message.conversationId.in_(conversation_ids))
                )
            for model in USER_OWNED_MODELS:
                await self.db.execute(delete(model).where(model.userId == user_id))
            await UsersRepository(self.db).delete(user)

        await self._clear_cache(user_id, task_ids, workspace_ids, group_ids, conversation_ids)

    async def _ids(self, column, condition) -> list[str]:
        result = await self.db.execute(select(column).where(condition))
        return [str(row) for row in result.scalars().all()]

    async def _stop_calendar_sync(self, user_id: str) -> None:
        from app.modules.auth.services.auth_service import AuthService
        from app.modules.google_calendar.services.google_calendar_service import (
            GoogleCalendarService,
        )
        from app.modules.task.services.scheduler_service import SchedulerService
        from app.modules.task.services.tasks.tasks_service import TasksService

        try:
            auth_serv = AuthService(self.db)
            tasks_serv = TasksService(self.db)
            gc_service = GoogleCalendarService(
                self.db, auth_serv, tasks_serv, SchedulerService()
            )
            await gc_service.stop_watching_calendar(user_id)
        except Exception:
            logger.exception("Could not stop calendar sync for user %s", user_id)

    async def _revoke_google_token(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": refresh_token},
                )
        except Exception:
            logger.exception("Could not revoke Google token on account deletion")

    def _delete_avatars(self, user_id: str) -> None:
        from app.modules.storage.services.storage_service import (
            delete_user_avatar_objects,
        )

        try:
            delete_user_avatar_objects(user_id)
        except Exception:
            logger.exception("Could not delete avatar objects for user %s", user_id)

    async def _clear_cache(
        self,
        user_id: str,
        task_ids: list[str],
        workspace_ids: list[str],
        group_ids: list[str],
        conversation_ids: list[str],
    ) -> None:
        keys = [
            f"tasks:active:user:{user_id}",
            f"signals:user:{user_id}",
            f"workspaces:user:{user_id}",
            f"project_groups:user:{user_id}",
            f"conversations:user:{user_id}",
        ]
        keys += [f"task:id:{i}" for i in task_ids]
        keys += [f"workspace:id:{i}" for i in workspace_ids]
        keys += [f"project_group:id:{i}" for i in group_ids]
        for i in conversation_ids:
            keys += [f"conversation:id:{i}", f"conversation:messages:{i}"]
        for key in keys:
            await cache.delete(key)
