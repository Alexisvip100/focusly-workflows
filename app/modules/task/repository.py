from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, delete
from app.models import Task, Tag, TimeBlock, FocusSession, User

class TasksRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, task: Task) -> Task:
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def get_by_id(self, task_id: str) -> Task | None:
        result = await self.db.execute(select(Task).where(Task.id == task_id))
        return result.scalars().first()

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
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None)
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

    async def save(self, task: Task) -> Task:
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def delete(self, task: Task) -> None:
        await self.db.delete(task)
        await self.db.commit()

    async def delete_google_tasks_by_user(self, user_id: str) -> int:
        result = await self.db.execute(
            delete(Task).where(
                Task.userId == user_id,
                Task.source == "google"
            )
        )
        await self.db.commit()
        return result.rowcount

    async def get_tasks_for_warning(self, start_min: float, end_min: float, is_last_minute: bool = False) -> list[tuple[Task, User]]:
        from sqlalchemy import func
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        notif_time = func.coalesce(Task.estimated_start_date, Task.deadline)
        
        status_filter = ["completed", "cancelled", "Completed"]
        
        query = select(Task, User).join(User, User.id == Task.userId).where(
            Task.deletedAt == None,
            Task.status.notin_(status_filter)
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
        # Search by id first, then by name
        result = await self.db.execute(select(Tag).where(Tag.id == name))
        tag = result.scalars().first()
        if not tag:
            result = await self.db.execute(select(Tag).where(Tag.name == name))
            tag = result.scalars().first()
        return tag

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
