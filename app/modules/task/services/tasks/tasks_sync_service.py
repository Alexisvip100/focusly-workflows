from __future__ import annotations

import logging
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.modules.task.services.scheduler_service import SchedulerService
from app.modules.user.repository import UsersRepository
from .tasks_mapper import map_task_to_google_event, task_to_dict

logger = logging.getLogger(__name__)


class TasksSyncService:
    """Handles external calendar synchronization and background scheduling pipelines."""

    def __init__(
        self,
        db: AsyncSession,
        google_calendar_service=None,
        socket_server=None,
    ):
        self.db = db
        self.google_calendar_service = google_calendar_service
        self.socket_server = socket_server
        self.scheduler_service = SchedulerService()

    async def sync_create_to_google(
        self, user_id: str | None, task_data: dict[str, Any]
    ) -> None:
        """Mirrors newly created task into Google Calendar if user has integration active."""
        if not user_id or not self.google_calendar_service:
            return

        try:
            user = await UsersRepository(self.db).get_by_id(user_id)
            if user and user.googleRefreshToken:
                google_event_body = map_task_to_google_event(task_data)
                google_event = await self.google_calendar_service.create_event(
                    user_id, google_event_body
                )
                if google_event and google_event.get("id"):
                    task_data["google_event_id"] = google_event["id"]
                    task_data["task_type"] = "GoogleTask"
                    task_data["google_synced_etag"] = google_event.get("etag")
        except Exception:
            logger.warning(
                "Failed to create mirrored Google Calendar event for a new task (user %s)",
                user_id,
                exc_info=True,
            )

    async def sync_update_to_google(self, task: Task) -> None:
        """Pushes task updates back to Google Calendar."""
        if (
            not task.google_event_id
            or task.task_type != "GoogleTask"
            or not self.google_calendar_service
        ):
            return

        try:
            updated_task_dict = task_to_dict(task)
            google_event_body = map_task_to_google_event(updated_task_dict)
            google_event = await self.google_calendar_service.patch_event(
                task.userId, task.google_event_id, google_event_body
            )
            task.google_synced_etag = google_event.get("etag")
            # pyrefly: ignore [bad-assignment]
            task.sync_status = "synced"
        except Exception:
            # pyrefly: ignore [bad-assignment]
            task.sync_status = "sync_error"
            logger.warning(
                "Failed to push task %s to Google Calendar event %s",
                task.id,
                task.google_event_id,
                exc_info=True,
            )

    async def sync_delete_to_google(self, task: Task) -> None:
        """Removes the mirrored event in Google Calendar upon task deletion."""
        if (
            task.google_event_id
            and task.userId
            and self.google_calendar_service
        ):
            try:
                await self.google_calendar_service.delete_event(
                    task.userId, task.google_event_id
                )
            except Exception:
                pass

    async def trigger_scheduler_pipeline(self, user_id: str | None) -> None:
        """Runs the scheduling optimizer pipeline for a specific user."""
        if user_id:
            await self.scheduler_service.run_scheduling_pipeline(
                user_id, self.db, self.socket_server
            )

    async def trigger_scheduler_pipeline_for_users(self, user_ids: set[str]) -> None:
        """Runs the scheduler pipeline for multiple users."""
        for u_id in user_ids:
            await self.trigger_scheduler_pipeline(u_id)
