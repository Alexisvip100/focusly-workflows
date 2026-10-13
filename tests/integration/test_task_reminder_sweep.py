"""The reminder sweep on the real Postgres: it warns, marks the task and
keeps the inbox notification, once. With mocks the bug didn't show: saving a
task without commit left updatedAt (onupdate=func.now()) expired, and caching
it lazy-loaded outside the async context (MissingGreenlet), so the sweep
crashed after emitting and the same warning went out again every minute.

Opt-in, it writes a temporary user and tasks to the database in DATABASE_URL:
    RUN_DB_TESTS=1 .venv/bin/python -m pytest tests/integration/test_task_reminder_sweep.py
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import Notification, Task
from app.modules.notification.services import task_notifier_service as notifier
from app.modules.user.domain.entities.user import User

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("RUN_DB_TESTS") != "1",
        reason="writes to the database: set RUN_DB_TESTS=1",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def world(monkeypatch):
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    user_id = f"reminder-test-{uuid.uuid4()}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def task(suffix: str, minutes: float, **over) -> Task:
        start = now + timedelta(minutes=minutes)
        fields = dict(
            id=f"{user_id}-{suffix}",
            userId=user_id,
            title=f"Reminder {suffix}",
            notes="",
            status="Scheduled",
            estimated_start_date=start,
            estimated_end_date=start + timedelta(minutes=30),
            notified=False,
            lastMinuteNotified=False,
        )
        fields.update(over)
        return Task(**fields)

    async with factory() as session:
        session.add(User(id=user_id, email=f"{user_id}@example.com", name="Reminder"))
        await session.flush()
        session.add_all(
            [
                task("five", 5),
                task("one", 1.5, notified=True),
                task("done", 5, status="Done"),
                task("later", 30),
            ]
        )
        await session.commit()

    emit = AsyncMock()
    monkeypatch.setattr(notifier, "async_session_local", factory)
    monkeypatch.setattr(notifier.sio, "emit", emit)
    try:
        yield factory, user_id, emit
    finally:
        async with factory() as session:
            await session.execute(
                delete(Notification).where(Notification.userId == user_id)
            )
            await session.execute(delete(Task).where(Task.userId == user_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()


async def test_a_sweep_warns_marks_and_files_each_reminder_once(world):
    factory, user_id, emit = world

    await notifier._check_and_notify_once()
    await notifier._check_and_notify_once()  # the next minute: nothing new

    sent = [(c.args[1]["taskId"], c.args[1]["type"]) for c in emit.await_args_list]
    assert sorted(sent) == [(f"{user_id}-five", "5min"), (f"{user_id}-one", "1min")]

    async with factory() as session:
        flags = dict(
            (
                await session.execute(
                    select(Task.id, Task.notified).where(Task.userId == user_id)
                )
            ).all()
        )
        assert flags[f"{user_id}-five"] is True
        assert flags[f"{user_id}-done"] is False  # finished: never warned
        assert flags[f"{user_id}-later"] is False  # not yet
        inbox = (
            (
                await session.execute(
                    select(Notification.relatedTaskId).where(
                        Notification.userId == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(inbox) == [f"{user_id}-five", f"{user_id}-one"]
