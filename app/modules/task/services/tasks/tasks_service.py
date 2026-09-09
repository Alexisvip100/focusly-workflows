import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified

from app.database import transaction_scope
from app.models import Task, Workspace
from app.modules.task.schemas.tasks import TaskCreateSchema
from app.modules.task.repository import TasksRepository
from app.modules.workspace.repository import WorkspacesRepository
from .tasks_filter_services import TasksFilterService
from .tasks_mapper import task_to_dict, parse_naive_dt, map_task_to_google_event
from .tasks_sync_service import TasksSyncService


class TasksService:
    tasksFilter = TasksFilterService()

    def __init__(
        self, db: AsyncSession, google_calendar_service=None, socket_server=None
    ):
        self.db = db
        self.repository = TasksRepository(db)
        self.sync_service = TasksSyncService(
            db=db,
            google_calendar_service=google_calendar_service,
            socket_server=socket_server,
        )
        # Expose these for external tests or direct access
        self.google_calendar_service = google_calendar_service
        self.socket_server = socket_server
        self.scheduler_service = self.sync_service.scheduler_service

    def _apply_filters_and_sorting(
        self,
        tasks: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self.tasksFilter.apply_filters_and_sorting(tasks, filters, sort)

    def _map_to_dict(self, t: Task) -> dict[str, Any]:
        return task_to_dict(t)

    def _map_task_to_google_event(self, task: dict[str, Any]) -> dict[str, Any]:
        return map_task_to_google_event(task)

    async def create(
        self,
        task_data: dict[str, Any],
        skip_scheduling: bool = False,
        skip_google_sync: bool = False,
        skip_existing_check: bool = False,
    ) -> dict[str, Any]:
        user_id = task_data.get("userId")
        google_event_id = task_data.get("google_event_id")

        # 1. Upsert check
        if google_event_id and user_id and not skip_existing_check:
            existing = await self.repository.get_by_google_event_id(
                user_id, google_event_id
            )
            if existing:
                return await self.update(
                    existing.id,
                    task_data,
                    skip_scheduling=skip_scheduling,
                    skip_google_sync=skip_google_sync,
                )

        # 2. Sync to Google Calendar (performed outside DB transaction)
        if user_id and not skip_google_sync and not google_event_id:
            await self.sync_service.sync_create_to_google(user_id, task_data)

        task_id = task_data.get("id") or str(uuid.uuid4())
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        task_input = TaskCreateSchema(**task_data)

        new_task = Task(
            id=task_id,
            userId=user_id,
            deadline=task_input.deadline or now,
            **task_input.model_dump(exclude={"deadline"}),
        )

        should_schedule = user_id and not skip_scheduling and new_task.status != "Backlog"

        try:
            async with transaction_scope(self.db):
                await self.repository.create(new_task)

                # 3. Trigger scheduler pipeline (within transaction, socket emission deferred)
                if should_schedule:
                    await self.sync_service.trigger_scheduler_pipeline(
                        user_id, emit_socket=False
                    )
        except Exception as e:
            # Compensating action: if Google Calendar event was created but DB transaction rolled back, delete event from Google
            if new_task.google_event_id and user_id and self.google_calendar_service:
                try:
                    await self.google_calendar_service.delete_event(
                        user_id, new_task.google_event_id
                    )
                except Exception:
                    pass
            raise e

        # 4. Emit Socket.IO only after DB transaction is successfully committed!
        if should_schedule:
            await self.sync_service.emit_schedule_updated(user_id)

        return task_to_dict(new_task)

    async def get_synced_google_ids(self, user_id: str) -> list[str]:
        google_tasks = await self.repository.get_synced_google_tasks_by_user(user_id)
        return [str(t.google_event_id) for t in google_tasks if t.google_event_id]

    async def find_one(self, id: str) -> dict[str, Any]:
        task = await self.repository.get_by_id(id)
        if not task:
            raise ValueError(f"Task with ID {id} not found")
        return task_to_dict(task)

    async def find_all(self) -> list[dict[str, Any]]:
        tasks = await self.repository.get_active_non_google_tasks()
        return [task_to_dict(t) for t in tasks]

    async def find_all_by_user(
        self,
        user_id: str,
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int | None = 24,
    ) -> dict[str, Any]:
        result = await self.repository.get_all_active_by_user(user_id)
        tasks = [task_to_dict(t) for t in result]

        # Aplicar filtros y orden
        tasks = self.tasksFilter.apply_filters_and_sorting(tasks, filters, sort)

        total = len(tasks)
        items = tasks[offset : offset + limit] if limit is not None else tasks[offset:]

        return {
            "items": items,
            "total": total,
        }

    async def find_paginated_by_user(
        self,
        user_id: str,
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        res = await self.find_all_by_user(
            user_id, filters, sort, offset=offset, limit=limit
        )
        return res["items"], res["total"]

    async def filter_by_status(
        self, filters: dict[str, Any], sort: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        tasks_list = await self.repository.get_active_non_google_tasks()
        tasks = [task_to_dict(t) for t in tasks_list]
        return self.tasksFilter.apply_filters_and_sorting(tasks, filters, sort)

    async def find_upcoming_tasks(
        self, start_date: datetime, end_date: datetime
    ) -> list[dict[str, Any]]:
        tasks = await self.repository.get_upcoming_tasks(start_date, end_date)
        return [task_to_dict(t) for t in tasks]

    async def find_last_minute_tasks(
        self, start_date: datetime, end_date: datetime
    ) -> list[dict[str, Any]]:
        tasks = await self.repository.get_last_minute_tasks(start_date, end_date)
        return [task_to_dict(t) for t in tasks]

    async def mark_as_notified(self, id: str) -> None:
        task = await self.repository.get_by_id(id)
        if task:
            task.notified = True
            await self.repository.save(task)

    async def mark_as_last_minute_notified(self, id: str) -> None:
        task = await self.repository.get_by_id(id)
        if task:
            task.lastMinuteNotified = True
            await self.repository.save(task)

    async def update(
        self,
        id: str,
        update_data: dict[str, Any],
        skip_scheduling: bool = False,
        skip_google_sync: bool = False,
    ) -> dict[str, Any]:
        task = await self.repository.get_by_id(id)
        if not task:
            raise ValueError(f"Task with ID {id} not found")

        has_changes = False

        for key, value in update_data.items():
            if hasattr(task, key):
                current_value = getattr(task, key)

                if key in ["estimated_start_date", "estimated_end_date", "deadline"]:
                    parsed_val = parse_naive_dt(value)
                    if current_value != parsed_val:
                        setattr(task, key, parsed_val)
                        has_changes = True
                elif key in ["subtasks", "time_logs", "collaborators"]:
                    if current_value != value:
                        setattr(task, key, value)
                        flag_modified(task, key)
                        has_changes = True
                else:
                    if current_value != value:
                        setattr(task, key, value)
                        has_changes = True

                        if key == "status":
                            if value == "Done" and not task.completedAt:
                                task.completedAt = datetime.now(timezone.utc).replace(tzinfo=None)
                            elif value != "Done" and task.completedAt:
                                task.completedAt = None

        should_schedule = task.userId and has_changes and not skip_scheduling

        if has_changes:
            task.updatedAt = datetime.now(timezone.utc).replace(tzinfo=None)

            # Sync update back to Google Calendar (performed outside DB transaction)
            if not skip_google_sync:
                await self.sync_service.sync_update_to_google(task)

            async with transaction_scope(self.db):
                await self.repository.save(task)
                if should_schedule:
                    await self.sync_service.trigger_scheduler_pipeline(
                        str(task.userId), emit_socket=False
                    )

        if should_schedule:
            await self.sync_service.emit_schedule_updated(str(task.userId))

        result_task = task_to_dict(task)
        result_task["_changed"] = has_changes
        return result_task

    async def delete(
        self, id: str, skip_scheduling: bool = False, skip_google_sync: bool = False
    ) -> None:
        task = await self.repository.get_by_id(id)
        if not task:
            raise ValueError(f"Task with ID {id} not found")

        # Sync deletion to Google Calendar (outside DB transaction)
        if not skip_google_sync:
            await self.sync_service.sync_delete_to_google(task)

        should_schedule = task.userId and not skip_scheduling

        # Release task references from workspaces, delete task, and recalculate scheduler atomically
        async with transaction_scope(self.db):
            workspaces_res = await self.db.execute(
                select(Workspace).where(Workspace.taskId == id)
            )
            workspaces_repo = WorkspacesRepository(self.db)
            for w in workspaces_res.scalars().all():
                w.taskId = None
                w.updatedAt = datetime.now(timezone.utc).replace(tzinfo=None)
                await workspaces_repo.save(w)

            # Hard delete (Físico)
            await self.repository.delete(task)

            if should_schedule:
                await self.sync_service.trigger_scheduler_pipeline(
                    str(task.userId), emit_socket=False
                )

        if should_schedule:
            await self.sync_service.emit_schedule_updated(str(task.userId))

    async def delete_many(self, ids: list[str]) -> None:
        user_ids: set[str] = set()
        for id in ids:
            task = await self.repository.get_by_id(id)
            if task and task.userId:
                user_ids.add(str(task.userId))
            await self.delete(id, skip_scheduling=True)

        await self.sync_service.trigger_scheduler_pipeline_for_users(user_ids)

    async def delete_workspace_tasks(self, workspace_id: str) -> None:
        result = await self.db.execute(
            select(Task).where(Task.workspaceId == workspace_id, Task.deletedAt == None)
        )
        tasks = result.scalars().all()
        user_ids: set[str] = {str(t.userId) for t in tasks if t.userId}

        for t in tasks:
            await self.delete(str(t.id), skip_scheduling=True)

        await self.sync_service.trigger_scheduler_pipeline_for_users(user_ids)
