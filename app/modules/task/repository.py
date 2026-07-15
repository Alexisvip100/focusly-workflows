from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, delete
from app.models import Task, Tag, TimeBlock, FocusSession, User
from app.redis import cache

INACTIVE_STATUSES = ["completed", "cancelled", "Completed"]

def serialize_task(t: Task) -> dict:
    return {
        "id": t.id,
        "userId": t.userId,
        "title": t.title,
        "notesEncrypted": t.notesEncrypted,
        "estimateTimer": t.estimateTimer,
        "realTimer": t.realTimer,
        "duration": t.duration,
        "priorityLevel": t.priorityLevel,
        "category": t.category,
        "color": t.color,
        "estimated_start_date": t.estimated_start_date.isoformat() if t.estimated_start_date else None,
        "estimated_end_date": t.estimated_end_date.isoformat() if t.estimated_end_date else None,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "status": t.status,
        "google_event_id": t.google_event_id,
        "source": t.source,
        "notified": t.notified,
        "lastMinuteNotified": t.lastMinuteNotified,
        "tags": t.tags,
        "links": t.links,
        "collaborators": t.collaborators,
        "use_ai": t.use_ai,
        "completedAt": t.completedAt.isoformat() if t.completedAt else None,
        "createdAt": t.createdAt.isoformat() if t.createdAt else None,
        "updatedAt": t.updatedAt.isoformat() if t.updatedAt else None,
        "deletedAt": t.deletedAt.isoformat() if t.deletedAt else None
    }

def deserialize_task(data: dict) -> Task:
    t = Task(
        id=data["id"],
        userId=data["userId"],
        title=data["title"],
        notesEncrypted=data["notesEncrypted"],
        estimateTimer=data["estimateTimer"],
        realTimer=data["realTimer"],
        duration=data["duration"],
        priorityLevel=data["priorityLevel"],
        category=data["category"],
        color=data["color"],
        estimated_start_date=datetime.fromisoformat(data["estimated_start_date"]) if data.get("estimated_start_date") else None,
        estimated_end_date=datetime.fromisoformat(data["estimated_end_date"]) if data.get("estimated_end_date") else None,
        deadline=datetime.fromisoformat(data["deadline"]) if data.get("deadline") else None,
        status=data["status"],
        google_event_id=data["google_event_id"],
        source=data["source"],
        notified=data["notified"],
        lastMinuteNotified=data["lastMinuteNotified"],
        tags=data["tags"],
        links=data["links"],
        collaborators=data["collaborators"],
        use_ai=data["use_ai"]
    )
    t.completedAt = datetime.fromisoformat(data["completedAt"]) if data.get("completedAt") else None
    t.createdAt = datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else None
    t.updatedAt = datetime.fromisoformat(data["updatedAt"]) if data.get("updatedAt") else None
    t.deletedAt = datetime.fromisoformat(data["deletedAt"]) if data.get("deletedAt") else None
    return t

class TasksRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, task: Task, commit: bool = True) -> Task:
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

    async def get_by_google_event_id(self, user_id: str, google_event_id: str) -> Task | None:
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.google_event_id == google_event_id,
                Task.deletedAt == None
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
                or_(Task.source != "google", Task.source == None)
            )
        )
        tasks = list(result.scalars().all())
        await cache.set(f"tasks:active:user:{user_id}", [serialize_task(t) for t in tasks])
        return tasks

    async def get_all_non_deleted_by_user(self, user_id: str) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.deletedAt == None
            )
        )
        return list(result.scalars().all())

    async def get_synced_google_tasks_by_user(self, user_id: str) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                Task.google_event_id != None
            )
        )
        return list(result.scalars().all())

    async def get_active_non_google_tasks(self, user_id: str | None = None) -> list[Task]:
        query = select(Task).where(
            Task.deletedAt == None,
            or_(Task.source != "google", Task.source == None)
        )
        if user_id is not None:
            query = query.where(Task.userId == user_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_upcoming_tasks(self, start_date: datetime, end_date: datetime) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.deadline >= start_date,
                Task.deadline <= end_date,
                Task.notified == False,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None)
            )
        )
        return list(result.scalars().all())

    async def get_last_minute_tasks(self, start_date: datetime, end_date: datetime) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.deadline >= start_date,
                Task.deadline <= end_date,
                Task.lastMinuteNotified == False,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None)
            )
        )
        return list(result.scalars().all())

    async def save(self, task: Task, commit: bool = True) -> Task:
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

    async def delete(self, task: Task, commit: bool = True) -> None:
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
            delete(Task).where(
                Task.userId == user_id,
                Task.source == "google"
            ).returning(Task.id)
        )
        deleted_ids = list(result.scalars().all())
        await self.db.commit()
        await cache.delete(f"tasks:active:user:{user_id}")
        for t_id in deleted_ids:
            await cache.delete(f"task:id:{t_id}")
        await cache.delete(f"signals:user:{user_id}")
        return len(deleted_ids)

    async def get_tasks_for_warning(self, start_min: float, end_min: float, is_last_minute: bool = False) -> list[tuple[Task, User]]:
        from sqlalchemy import func
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        notif_time = func.coalesce(Task.estimated_start_date, Task.deadline)
        
        query = select(Task, User).join(User, User.id == Task.userId).where(
            Task.deletedAt == None,
            Task.status.notin_(INACTIVE_STATUSES)
        )
        
        if is_last_minute:
            query = query.where(
                or_(Task.lastMinuteNotified == False, Task.lastMinuteNotified.is_(None)),
                notif_time >= now + timedelta(minutes=start_min),
                notif_time <= now + timedelta(minutes=end_min)
            )
        else:
            query = query.where(
                or_(Task.notified == False, Task.notified.is_(None)),
                notif_time >= now + timedelta(minutes=start_min),
                notif_time <= now + timedelta(minutes=end_min)
            )
            
        result = await self.db.execute(query)
        return list(result.all())


class TagsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, tag: Tag) -> Tag:
        self.db.add(tag)
        await self.db.commit()
        await self.db.refresh(tag)
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

    async def create(self, time_block: TimeBlock) -> TimeBlock:
        self.db.add(time_block)
        await self.db.commit()
        await self.db.refresh(time_block)
        return time_block

    async def create_many(self, time_blocks: list[TimeBlock]) -> None:
        self.db.add_all(time_blocks)
        await self.db.commit()

    async def replace_focus_blocks(self, user_id: str, new_blocks: list[TimeBlock]) -> None:
        await self.db.execute(
            delete(TimeBlock).where(TimeBlock.userId == user_id, TimeBlock.blockType == "Focus_Block")
        )
        if new_blocks:
            self.db.add_all(new_blocks)
        await self.db.commit()

    async def get_by_id(self, block_id: str) -> TimeBlock | None:
        result = await self.db.execute(select(TimeBlock).where(TimeBlock.id == block_id))
        return result.scalars().first()

    async def get_all(self) -> list[TimeBlock]:
        result = await self.db.execute(select(TimeBlock))
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: str) -> list[TimeBlock]:
        result = await self.db.execute(select(TimeBlock).where(TimeBlock.userId == user_id))
        return list(result.scalars().all())

    async def get_synced_google_ids(self, user_id: str) -> list[str]:
        result = await self.db.execute(
            select(TimeBlock.externalEventId).where(
                TimeBlock.userId == user_id,
                TimeBlock.source == "Google"
            )
        )
        return [r for r in result.scalars().all() if r]

    async def delete_many_focus_blocks(self, user_id: str) -> None:
        await self.db.execute(
            delete(TimeBlock).where(TimeBlock.userId == user_id, TimeBlock.blockType == "Focus_Block")
        )
        await self.db.commit()

    async def delete_many_by_external_ids(self, user_id: str, external_ids: list[str]) -> None:
        await self.db.execute(
            delete(TimeBlock).where(TimeBlock.userId == user_id, TimeBlock.externalEventId.in_(external_ids))
        )
        await self.db.commit()

    async def save(self, time_block: TimeBlock) -> TimeBlock:
        await self.db.commit()
        await self.db.refresh(time_block)
        return time_block

    async def delete(self, time_block: TimeBlock) -> None:
        await self.db.delete(time_block)
        await self.db.commit()


class FocusSessionsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, session: FocusSession) -> FocusSession:
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_by_id(self, session_id: str) -> FocusSession | None:
        result = await self.db.execute(select(FocusSession).where(FocusSession.id == session_id))
        return result.scalars().first()

    async def get_all(self) -> list[FocusSession]:
        result = await self.db.execute(select(FocusSession))
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: str) -> list[FocusSession]:
        result = await self.db.execute(select(FocusSession).where(FocusSession.userId == user_id))
        return list(result.scalars().all())

    async def save(self, session: FocusSession) -> FocusSession:
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def delete(self, session: FocusSession) -> None:
        await self.db.delete(session)
        await self.db.commit()
