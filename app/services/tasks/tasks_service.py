import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import Task, User, Workspace
from app.schemas.tasks import TaskCreateSchema
from app.services.scheduler.scheduler_service import SchedulerService


class TasksService:
    def __init__(
        self, db: AsyncSession, google_calendar_service=None, socket_server=None
    ):
        self.db = db
        self.google_calendar_service = google_calendar_service
        self.scheduler_service = SchedulerService()
        self.socket_server = socket_server

    def _map_to_dict(self, t: Task) -> dict[str, Any]:
        return {
            "id": t.id,
            "userId": t.userId,
            "title": t.title,
            "notesEncrypted": t.notesEncrypted,
            "estimateTimer": t.estimateTimer,
            "realTimer": t.realTimer,
            "duration": t.duration.isoformat() if t.duration else None,
            "priorityLevel": t.priorityLevel,
            "category": t.category,
            "color": t.color,
            "estimated_start_date": t.estimated_start_date.isoformat()
            if t.estimated_start_date
            else None,
            "estimated_end_date": t.estimated_end_date.isoformat()
            if t.estimated_end_date
            else None,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "status": t.status,
            "completedAt": t.completedAt.isoformat() if t.completedAt else None,
            "createdAt": t.createdAt.isoformat() if t.createdAt else None,
            "updatedAt": t.updatedAt.isoformat() if t.updatedAt else None,
            "deletedAt": t.deletedAt.isoformat() if t.deletedAt else None,
            "tags": t.tags or [],
            "filters": t.filters or {},
            "links": t.links or [],
            "task_type": t.task_type or "PlatformTask",
            "google_event_id": t.google_event_id,
            "source": t.source or "platform",
            "sync_status": t.sync_status or "synced",
            "collaborators": t.collaborators or [],
            "notified": t.notified or False,
            "lastMinuteNotified": t.lastMinuteNotified or False,
            "use_ai": t.use_ai or False,
            "workspaceId": t.workspaceId,
        }

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
            result = await self.db.execute(
                select(Task).where(
                    Task.userId == user_id,
                    Task.google_event_id == google_event_id,
                    Task.deletedAt == None,
                )
            )
            existing = result.scalars().first()
            if existing:
                print(
                    f"[UPSERT] Task with google_event_id {google_event_id} already exists. Updating instead."
                )
                return await self.update(
                    existing.id,
                    task_data,
                    skip_scheduling=skip_scheduling,
                    skip_google_sync=skip_google_sync,
                )

        # 2. Sync to Google Calendar
        if user_id and not skip_google_sync and not google_event_id:
            try:
                user_res = await self.db.execute(select(User).where(User.id == user_id))
                user = user_res.scalars().first()
                if user and user.googleRefreshToken and self.google_calendar_service:
                    google_event_body = self._map_task_to_google_event(task_data)
                    google_event = await self.google_calendar_service.create_event(
                        user_id, google_event_body
                    )
                    if google_event and google_event.get("id"):
                        task_data["google_event_id"] = google_event["id"]
                        task_data["task_type"] = "GoogleTask"
            except Exception as e:
                print("Error creating Google Calendar event on task creation:", e)

        task_id = task_data.get("id") or str(uuid.uuid4())
        now = datetime.utcnow()

        def parse_dt(val):
            if not val:
                return None
            if isinstance(val, datetime):
                return val.replace(tzinfo=None)
            if isinstance(val, str):
                try:
                    val = val.replace("Z", "+00:00")
                    return datetime.fromisoformat(val).replace(tzinfo=None)
                except:
                    return None
            return None

        task_input = TaskCreateSchema(**task_data)

        new_task = Task(
            id=task_id,
            userId=user_id,
            deadline=task_input.deadline or now,
            **task_input.model_dump(
                exclude={"deadline"}
            ),  # Desempaqueta el resto de campos ya procesados
        )
        self.db.add(new_task)
        await self.db.commit()
        await self.db.refresh(new_task)

        if user_id and not skip_scheduling:
            await self.scheduler_service.run_scheduling_pipeline(
                user_id, self.db, self.socket_server
            )

        return self._map_to_dict(new_task)

    async def get_synced_google_ids(self, user_id: str) -> list[str]:
        result = await self.db.execute(
            select(Task.google_event_id).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                Task.google_event_id != None,
            )
        )
        return [r for r in result.scalars().all() if r]

    async def find_one(self, id: str) -> dict[str, Any]:
        result = await self.db.execute(select(Task).where(Task.id == id))
        task = result.scalars().first()
        if not task:
            raise ValueError(f"Task with ID {id} not found")
        return self._map_to_dict(task)

    async def find_all(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Task).where(
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        return [self._map_to_dict(t) for t in result.scalars().all()]

    async def find_all_by_user(
        self,
        user_id: str,
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        tasks = [self._map_to_dict(t) for t in result.scalars().all()]
        return self._apply_filters_and_sorting(tasks, filters, sort)

    async def find_paginated_by_user(
        self,
        user_id: str,
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        tasks = await self.find_all_by_user(user_id, filters, sort)
        total_count = len(tasks)
        end_idx = (offset + limit) if limit is not None else total_count
        paginated_tasks = tasks[offset:end_idx]
        return paginated_tasks, total_count

    async def filter_by_status(
        self, filters: dict[str, Any], sort: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Task).where(
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        tasks = [self._map_to_dict(t) for t in result.scalars().all()]
        return self._apply_filters_and_sorting(tasks, filters, sort)

    async def find_upcoming_tasks(
        self, start_date: datetime, end_date: datetime
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Task).where(
                Task.deadline >= start_date,
                Task.deadline <= end_date,
                Task.notified == False,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        return [self._map_to_dict(t) for t in result.scalars().all()]

    async def find_last_minute_tasks(
        self, start_date: datetime, end_date: datetime
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Task).where(
                Task.deadline >= start_date,
                Task.deadline <= end_date,
                Task.lastMinuteNotified == False,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        return [self._map_to_dict(t) for t in result.scalars().all()]

    async def mark_as_notified(self, id: str) -> None:
        result = await self.db.execute(select(Task).where(Task.id == id))
        task = result.scalars().first()
        if task:
            task.notified = True
            await self.db.commit()

    async def mark_as_last_minute_notified(self, id: str) -> None:
        result = await self.db.execute(select(Task).where(Task.id == id))
        task = result.scalars().first()
        if task:
            task.lastMinuteNotified = True
            await self.db.commit()

    async def update(
        self,
        id: str,
        update_data: dict[str, Any],
        skip_scheduling: bool = False,
        skip_google_sync: bool = False,
    ) -> dict[str, Any]:
        result = await self.db.execute(select(Task).where(Task.id == id))
        task = result.scalars().first()
        if not task:
            # If update on non-existent task, we create it
            return await self.create(
                update_data,
                skip_scheduling=skip_scheduling,
                skip_google_sync=skip_google_sync,
            )

        has_changes = False

        def parse_dt(val):
            if not val:
                return None
            if isinstance(val, datetime):
                # Strip tzinfo so it's always naive (TIMESTAMP WITHOUT TIME ZONE)
                return val.replace(tzinfo=None)
            if isinstance(val, str):
                try:
                    val = val.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(val)
                    # Always return naive datetime (strip UTC offset)
                    return dt.replace(tzinfo=None)
                except:
                    return None
            return None

        # Reset notified statuses if deadline updates
        if "deadline" in update_data and update_data["deadline"]:
            new_dl = parse_dt(update_data["deadline"])
            if task.deadline != new_dl:
                task.deadline = new_dl
                task.notified = False
                task.lastMinuteNotified = False
                has_changes = True

        for key, value in update_data.items():
            if key in ["id", "createdAt", "updatedAt", "deletedAt", "deadline"]:
                continue

            if hasattr(task, key):
                current_val = getattr(task, key)
                if key in [
                    "duration",
                    "estimated_start_date",
                    "estimated_end_date",
                    "completedAt",
                ]:
                    dt_val = parse_dt(value)
                    if current_val != dt_val:
                        setattr(task, key, dt_val)
                        has_changes = True
                else:
                    if current_val != value:
                        setattr(task, key, value)
                        has_changes = True

        if has_changes:
            task.updatedAt = datetime.utcnow()

            # Sync update back to Google Calendar if requested and task is a GoogleTask
            if (
                not skip_google_sync
                and task.google_event_id
                and task.task_type == "GoogleTask"
                and self.google_calendar_service
            ):
                try:
                    updated_task_dict = self._map_to_dict(task)
                    google_event_body = self._map_task_to_google_event(
                        updated_task_dict
                    )
                    print(
                        f"[GOOGLE CAL] Syncing update of GoogleTask {task.id} (Event: {task.google_event_id}) to Google Calendar..."
                    )
                    await self.google_calendar_service.patch_event(
                        task.userId, task.google_event_id, google_event_body
                    )
                except Exception as e:
                    print(
                        f"Error syncing task update to Google Calendar for task {task.id}: {e}"
                    )

            await self.db.commit()
            await self.db.refresh(task)

        if task.userId and has_changes and not skip_scheduling:
            await self.scheduler_service.run_scheduling_pipeline(
                task.userId, self.db, self.socket_server
            )

        # Re-fetch mapping
        result_task = self._map_to_dict(task)
        result_task["_changed"] = has_changes
        return result_task

    async def delete(
        self, id: str, skip_scheduling: bool = False, skip_google_sync: bool = False
    ) -> None:
        result = await self.db.execute(select(Task).where(Task.id == id))
        task = result.scalars().first()
        if not task:
            raise ValueError(f"Task with ID {id} not found")

        task_type = task.task_type or "PlatformTask"

        # Sync deletion to Google Calendar
        if task.google_event_id and task.userId and not skip_google_sync:
            if self.google_calendar_service:
                try:
                    await self.google_calendar_service.delete_event(
                        task.userId, task.google_event_id
                    )
                except Exception as e:
                    print("Failed to delete synced Google Calendar event:", e)

        # Release task references from workspaces
        workspaces_res = await self.db.execute(
            select(Workspace).where(Workspace.taskId == id)
        )
        for w in workspaces_res.scalars().all():
            w.taskId = None
            w.updatedAt = datetime.utcnow()

        # Hard delete (Físico)
        await self.db.delete(task)
        await self.db.commit()

        if task.userId and not skip_scheduling:
            await self.scheduler_service.run_scheduling_pipeline(
                task.userId, self.db, self.socket_server
            )

    async def delete_many(self, ids: list[str]) -> None:
        user_ids = set()
        for id in ids:
            result = await self.db.execute(select(Task).where(Task.id == id))
            task = result.scalars().first()
            if task:
                if task.userId:
                    user_ids.add(task.userId)
                await self.delete(id, skip_scheduling=True)

        for u_id in user_ids:
            await self.scheduler_service.run_scheduling_pipeline(
                u_id, self.db, self.socket_server
            )

    async def delete_workspace_tasks(self, workspace_id: str) -> None:
        result = await self.db.execute(
            select(Task).where(Task.workspaceId == workspace_id, Task.deletedAt == None)
        )
        tasks = result.scalars().all()
        user_ids = set()

        for t in tasks:
            if t.userId:
                user_ids.add(t.userId)
            await self.delete(t.id, skip_scheduling=True)

        for u_id in user_ids:
            await self.scheduler_service.run_scheduling_pipeline(
                u_id, self.db, self.socket_server
            )

    def _apply_filters_and_sorting(
        self,
        tasks: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        mapped = list(tasks)

        if filters:
            if filters.get("status") and len(filters["status"]) > 0:
                mapped = [t for t in mapped if t.get("status") in filters["status"]]

            if filters.get("priorityLevel") and len(filters["priorityLevel"]) > 0:
                # If priority level query contains >= 3, include higher levels
                levels = filters["priorityLevel"]
                if any(p >= 3 for p in levels):
                    mapped = [
                        t
                        for t in mapped
                        if t.get("priorityLevel", 0) >= 3
                        or t.get("priorityLevel") in levels
                    ]
                else:
                    mapped = [t for t in mapped if t.get("priorityLevel") in levels]

            if filters.get("category") and len(filters["category"]) > 0:
                mapped = [t for t in mapped if t.get("category") in filters["category"]]

            if filters.get("startDate") or filters.get("endDate"):

                def parse_date(d_str):
                    if not d_str:
                        return None
                    return datetime.fromisoformat(d_str.replace("Z", "+00:00"))

                start_date = parse_date(filters.get("startDate"))
                end_date = parse_date(filters.get("endDate"))

                filtered_by_date = []
                for t in mapped:
                    date_to_use_str = (
                        t.get("createdAt")
                        if (t.get("status") == "Done" or not t.get("deadline"))
                        else t.get("deadline")
                    )
                    if not date_to_use_str:
                        continue
                    date_to_use = datetime.fromisoformat(date_to_use_str)

                    # Convert start/end to offset naive if date_to_use is naive
                    if date_to_use.tzinfo is None:
                        if start_date and start_date.tzinfo is not None:
                            start_date = start_date.replace(tzinfo=None)
                        if end_date and end_date.tzinfo is not None:
                            end_date = end_date.replace(tzinfo=None)

                    if start_date and date_to_use < start_date:
                        continue
                    if end_date and date_to_use > end_date:
                        continue
                    filtered_by_date.append(t)
                mapped = filtered_by_date

            if filters.get("searchTerm"):
                term = filters["searchTerm"].lower()
                mapped = [
                    t
                    for t in mapped
                    if term in t.get("title", "").lower()
                    or term in (t.get("notesEncrypted") or "").lower()
                ]

        if sort and sort.get("sort"):
            field_map = {
                "deadline": "deadline",
                "priority_level": "priorityLevel",
                "estimate_minutes": "estimateTimer",
                "created_at": "createdAt",
            }
            sort_field = field_map.get(sort["sort"], sort["sort"])
            direction = -1 if sort.get("order", "asc").lower() == "desc" else 1

            def sort_key(t):
                val = t.get(sort_field)
                if val is None:
                    return float("inf") if direction == 1 else float("-inf")
                if isinstance(val, str):
                    try:
                        return datetime.fromisoformat(val).timestamp()
                    except:
                        return val
                return val

            mapped.sort(key=sort_key, reverse=(direction == -1))

        return mapped

    def _map_task_to_google_event(self, task: dict[str, Any]) -> dict[str, Any]:
        def parse_naive(val):
            """Parse a datetime string or object and always return a naive (offset-free) datetime."""
            if not val:
                return None
            if isinstance(val, datetime):
                return val.replace(tzinfo=None)
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(
                        tzinfo=None
                    )
                except:
                    return None
            return None

        deadline_str = task.get("deadline")
        deadline = parse_naive(deadline_str) or datetime.utcnow()

        start = parse_naive(task.get("estimated_start_date")) or deadline

        end = parse_naive(task.get("estimated_end_date"))
        if not end:
            end = start + timedelta(minutes=(task.get("estimateTimer") or 30))

        clean_desc = task.get("notesEncrypted") or ""
        import re

        clean_desc = re.sub(r"\[COLOR:(.*?)\]", "", clean_desc)
        clean_desc = re.sub(r"\[START_DATE:(.*?)\]", "", clean_desc).strip()

        collaborators = task.get("collaborators") or []

        return {
            "summary": task.get("title", "Untitled Focusly Task"),
            "description": clean_desc,
            "start": {"dateTime": start.isoformat() + "Z"},
            "end": {"dateTime": end.isoformat() + "Z"},
            "attendees": [
                {"email": c["email"], "displayName": c.get("name", "")}
                for c in collaborators
                if c.get("email")
            ],
        }
