from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, and_, delete, func, DateTime
from app.models import Task, Tag, TimeBlock, FocusSession, User
from app.redis import cache
from app.modules.task.services.tasks.tasks_filter_services import TasksFilterService

INACTIVE_STATUSES = ["completed", "cancelled", "Completed"]


def serialize_task(t: Task) -> dict:
    # Derived from Task.__table__.columns (rather than a hand-picked field
    # list) so a column added to the model is automatically cached too —
    # a field silently missing here previously caused it to read back as
    # None from a warm cache even though the DB row had the real value
    # (e.g. task_type, which broke the Google Calendar sync decision).
    data = {}
    for column in Task.__table__.columns:
        value = getattr(t, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        data[column.name] = value
    return data


def deserialize_task(data: dict) -> Task:
    kwargs = {}
    for column in Task.__table__.columns:
        if column.name not in data:
            # Cache entry written before this column existed: leave it
            # unset rather than guessing, so a later db.merge() keeps
            # whatever the persistent row already has for it.
            continue
        value = data[column.name]
        if value is not None and isinstance(column.type, DateTime):
            value = datetime.fromisoformat(value)
        kwargs[column.name] = value
    return Task(**kwargs)


def parse_filter_date(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    elif isinstance(val, datetime):
        dt = val
    else:
        return None

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class TasksRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, task: Task, commit: bool = False) -> Task:
        self.db.add(task)
        if commit:
            await self.db.commit()
            await self.db.refresh(task)
        else:
            await self.db.flush()
        await cache.set(f"task:id:{task.id}", serialize_task(task))
        await cache.delete(f"tasks:active:user:{task.userId}")
        await cache.delete(f"signals:user:{task.userId}")
        return task

    async def get_by_id(self, task_id: str) -> Task | None:
        cached = await cache.get(f"task:id:{task_id}")
        if cached:
            return deserialize_task(cached)
        result = await self.db.execute(select(Task).where(Task.id == task_id))
        task = result.scalars().first()
        if task:
            await cache.set(f"task:id:{task.id}", serialize_task(task))
        return task

    async def get_by_google_event_id(
        self, user_id: str, google_event_id: str
    ) -> Task | None:
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.google_event_id == google_event_id,
                Task.deletedAt == None,
            )
        )
        return result.scalars().first()

    async def get_all_active_by_user(self, user_id: str) -> list[Task]:
        cached = await cache.get(f"tasks:active:user:{user_id}")
        if cached is not None:
            return [deserialize_task(t) for t in cached]
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        tasks = list(result.scalars().all())
        await cache.set(
            f"tasks:active:user:{user_id}", [serialize_task(t) for t in tasks]
        )
        return tasks

    async def query_tasks_by_user(
        self,
        user_id: str,
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int | None = None,
        search: str = "",
    ) -> tuple[list[Task], int]:
        conditions = [
            Task.userId == user_id,
            Task.deletedAt == None,
            or_(Task.source != "google", Task.source == None),
        ]

        if filters:
            if filters.get("status") and len(filters["status"]) > 0:
                conditions.append(Task.status.in_(filters["status"]))

            target_ws = filters.get("workspace_id") or filters.get("workspaceId")
            if target_ws is not None:
                conditions.append(Task.workspaceId == str(target_ws))

            target_proj = filters.get("project_id") or filters.get("projectId")
            if target_proj is not None:
                conditions.append(Task.projectId == str(target_proj))

            if filters.get("has_project") is True or filters.get("hasProject") is True:
                conditions.append(
                    and_(
                        Task.projectId.is_not(None),
                        Task.projectId != "",
                        func.trim(Task.projectId) != "",
                    )
                )

            if filters.get("category") and len(filters["category"]) > 0:
                conditions.append(Task.category.in_(filters["category"]))

            if filters.get("priorityLevel") and len(filters["priorityLevel"]) > 0:
                levels = [int(p) for p in filters["priorityLevel"]]
                if any(p >= 3 for p in levels):
                    conditions.append(or_(Task.priorityLevel >= 3, Task.priorityLevel.in_(levels)))
                else:
                    conditions.append(Task.priorityLevel.in_(levels))

            if filters.get("searchTerm"):
                term = str(filters["searchTerm"]).strip()
                if term:
                    conditions.append(
                        or_(
                            Task.title.ilike(f"%{term}%"),
                            Task.notesEncrypted.ilike(f"%{term}%"),
                        )
                    )

            if filters.get("startDate") or filters.get("endDate"):
                effective_date = func.coalesce(
                    Task.estimated_start_date,
                    Task.deadline,
                    Task.completedAt,
                    Task.createdAt,
                )
                start_dt = parse_filter_date(filters.get("startDate"))
                if start_dt is not None:
                    conditions.append(effective_date >= start_dt)

                end_dt = parse_filter_date(filters.get("endDate"))
                if end_dt is not None:
                    conditions.append(effective_date <= end_dt)

        if search and search.strip():
            conditions.append(Task.title.ilike(f"%{search.strip()}%"))

        order_clauses = []
        user_sorted_created_at = False
        if sort and sort.get("sort"):
            field_map = {
                "deadline": Task.deadline,
                "priority_level": Task.priorityLevel,
                "estimate_minutes": Task.estimateTimer,
                "created_at": Task.createdAt,
            }
            col = field_map.get(sort["sort"])
            if col is not None:
                if sort["sort"] == "created_at":
                    user_sorted_created_at = True
                direction = sort.get("order", "asc").lower()
                if direction == "desc":
                    order_clauses.append(col.desc().nulls_last())
                else:
                    order_clauses.append(col.asc().nulls_last())

        if not user_sorted_created_at:
            order_clauses.append(Task.createdAt.desc().nulls_last())
        order_clauses.append(Task.id.asc())

        has_tags_filter = bool(filters and filters.get("tags") and len(filters["tags"]) > 0)

        if not has_tags_filter:
            count_query = select(func.count()).select_from(Task).where(*conditions)
            count_res = await self.db.execute(count_query)
            total = count_res.scalar() or 0

            items_query = (
                select(Task)
                .where(*conditions)
                .order_by(*order_clauses)
                .offset(offset)
            )
            if limit is not None:
                items_query = items_query.limit(limit)

            items_res = await self.db.execute(items_query)
            items = list(items_res.scalars().all())
            return items, total
        else:
            # Opción B: SQL pre-filtra todos los criterios no-tags con ORDER BY determinista sin limit/offset
            items_query = (
                select(Task)
                .where(*conditions)
                .order_by(*order_clauses)
            )
            candidates_res = await self.db.execute(items_query)
            candidates = list(candidates_res.scalars().all())

            filtered = TasksFilterService.filter_tags_only(candidates, filters["tags"])
            total = len(filtered)
            items = filtered[offset : offset + limit] if limit is not None else filtered[offset:]
            return items, total

    async def get_all_non_deleted_by_user(self, user_id: str) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(Task.userId == user_id, Task.deletedAt == None)
        )
        return list(result.scalars().all())

    async def get_active_non_google_tasks(self) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        return list(result.scalars().all())

    async def get_synced_google_tasks_by_user(self, user_id: str) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                Task.google_event_id != None,
                Task.source == "google",
            )
        )
        return list(result.scalars().all())

    async def get_upcoming_tasks(
        self, start_date: datetime, end_date: datetime
    ) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.deadline >= start_date,
                Task.deadline <= end_date,
                Task.notified == False,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        return list(result.scalars().all())

    async def get_last_minute_tasks(
        self, start_date: datetime, end_date: datetime
    ) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.deadline >= start_date,
                Task.deadline <= end_date,
                Task.lastMinuteNotified == False,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        return list(result.scalars().all())

    async def save(self, task: Task, commit: bool = False) -> Task:
        if task not in self.db:
            task = await self.db.merge(task)
        if commit:
            await self.db.commit()
            await self.db.refresh(task)
        else:
            await self.db.flush()
        await cache.set(f"task:id:{task.id}", serialize_task(task))
        await cache.delete(f"tasks:active:user:{task.userId}")
        await cache.delete(f"signals:user:{task.userId}")
        return task

    async def delete(self, task: Task, commit: bool = False) -> None:
        if task not in self.db:
            task = await self.db.merge(task)
        await self.db.delete(task)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await cache.delete(f"task:id:{task.id}")
        await cache.delete(f"tasks:active:user:{task.userId}")
        await cache.delete(f"signals:user:{task.userId}")

    async def delete_google_tasks_by_user(self, user_id: str) -> int:
        result = await self.db.execute(
            delete(Task)
            .where(Task.userId == user_id, Task.source == "google")
            .returning(Task.id)
        )
        deleted_ids = list(result.scalars().all())
        await self.db.flush()
        await cache.delete(f"tasks:active:user:{user_id}")
        for t_id in deleted_ids:
            await cache.delete(f"task:id:{t_id}")
        await cache.delete(f"signals:user:{user_id}")
        return len(deleted_ids)

    async def get_tasks_for_warning(
        self, start_min: float, end_min: float, is_last_minute: bool = False
    ) -> list[tuple[Task, User]]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        notif_time = func.coalesce(Task.estimated_start_date, Task.deadline)

        query = (
            select(Task, User)
            .join(User, User.id == Task.userId)
            .where(Task.deletedAt == None, Task.status.notin_(INACTIVE_STATUSES))
        )

        if is_last_minute:
            query = query.where(
                or_(
                    Task.lastMinuteNotified == False, Task.lastMinuteNotified.is_(None)
                ),
                notif_time >= now + timedelta(minutes=start_min),
                notif_time <= now + timedelta(minutes=end_min),
            )
        else:
            query = query.where(
                or_(Task.notified == False, Task.notified.is_(None)),
                notif_time >= now + timedelta(minutes=start_min),
                notif_time <= now + timedelta(minutes=end_min),
            )

        result = await self.db.execute(query)
        return [(t, u) for t, u in result.all()]


class TagsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, tag: Tag, commit: bool = False) -> Tag:
        self.db.add(tag)
        if commit:
            await self.db.commit()
            await self.db.refresh(tag)
        else:
            await self.db.flush()
        return tag

    async def get_by_id_or_name(self, name: str) -> Tag | None:
        result = await self.db.execute(
            select(Tag).where(or_(Tag.id == name, Tag.name == name))
        )
        return result.scalars().first()

    async def get_all(self) -> list[Tag]:
        result = await self.db.execute(select(Tag))
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: str) -> list[Tag]:
        result = await self.db.execute(select(Tag).where(Tag.userId == user_id))
        return list(result.scalars().all())


class TimeBlocksRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, time_block: TimeBlock, commit: bool = False) -> TimeBlock:
        self.db.add(time_block)
        if commit:
            await self.db.commit()
            await self.db.refresh(time_block)
        else:
            await self.db.flush()
        return time_block

    async def create_many(self, time_blocks: list[TimeBlock], commit: bool = False) -> None:
        self.db.add_all(time_blocks)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def replace_focus_blocks(
        self, user_id: str, new_blocks: list[TimeBlock], commit: bool = False
    ) -> None:
        await self.db.execute(
            delete(TimeBlock).where(
                TimeBlock.userId == user_id, TimeBlock.blockType == "Focus_Block"
            )
        )
        if new_blocks:
            self.db.add_all(new_blocks)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def get_by_id(self, block_id: str) -> TimeBlock | None:
        result = await self.db.execute(
            select(TimeBlock).where(TimeBlock.id == block_id)
        )
        return result.scalars().first()

    async def get_all(self) -> list[TimeBlock]:
        result = await self.db.execute(select(TimeBlock))
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: str) -> list[TimeBlock]:
        result = await self.db.execute(
            select(TimeBlock).where(TimeBlock.userId == user_id)
        )
        return list(result.scalars().all())

    async def get_synced_google_ids(self, user_id: str) -> list[str]:
        result = await self.db.execute(
            select(TimeBlock.externalEventId).where(
                TimeBlock.userId == user_id, TimeBlock.source == "Google"
            )
        )
        return [r for r in result.scalars().all() if r]

    async def delete_many_focus_blocks(self, user_id: str, commit: bool = False) -> None:
        await self.db.execute(
            delete(TimeBlock).where(
                TimeBlock.userId == user_id, TimeBlock.blockType == "Focus_Block"
            )
        )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def delete_many_by_external_ids(
        self, user_id: str, external_ids: list[str], commit: bool = False
    ) -> None:
        await self.db.execute(
            delete(TimeBlock).where(
                TimeBlock.userId == user_id, TimeBlock.externalEventId.in_(external_ids)
            )
        )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

    async def save(self, time_block: TimeBlock, commit: bool = False) -> TimeBlock:
        if commit:
            await self.db.commit()
            await self.db.refresh(time_block)
        else:
            await self.db.flush()
        return time_block

    async def delete(self, time_block: TimeBlock, commit: bool = False) -> None:
        await self.db.delete(time_block)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()


class FocusSessionsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, session: FocusSession, commit: bool = False) -> FocusSession:
        self.db.add(session)
        if commit:
            await self.db.commit()
            await self.db.refresh(session)
        else:
            await self.db.flush()
        return session

    async def get_by_id(self, session_id: str) -> FocusSession | None:
        result = await self.db.execute(
            select(FocusSession).where(FocusSession.id == session_id)
        )
        return result.scalars().first()

    async def get_all(self) -> list[FocusSession]:
        result = await self.db.execute(select(FocusSession))
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: str) -> list[FocusSession]:
        result = await self.db.execute(
            select(FocusSession).where(FocusSession.userId == user_id)
        )
        return list(result.scalars().all())

    async def save(self, session: FocusSession, commit: bool = False) -> FocusSession:
        if session not in self.db:
            session = await self.db.merge(session)
        if commit:
            await self.db.commit()
            await self.db.refresh(session)
        else:
            await self.db.flush()
        return session

    async def delete(self, session: FocusSession, commit: bool = False) -> None:
        if session not in self.db:
            session = await self.db.merge(session)
        await self.db.delete(session)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
