"""The scheduling pipeline writes TIMESTAMP WITHOUT TIME ZONE columns: an
aware datetime there makes asyncpg reject the UPDATE, which rolled back
every task creation that triggered scheduling."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.task.services.scheduler import scheduler_service as module
from app.modules.task.services.scheduler.scheduler_service import SchedulerService


@pytest.mark.anyio
async def test_scheduled_task_is_saved_with_naive_utc_dates(monkeypatch):
    task = SimpleNamespace(
        id="t1",
        estimated_start_date=None,
        estimated_end_date=None,
        status="Todo",
        updatedAt=None,
        notified=True,
        lastMinuteNotified=True,
    )
    tasks_repo = MagicMock()
    tasks_repo.get_all_active_by_user = AsyncMock(return_value=[])
    tasks_repo.get_by_id = AsyncMock(return_value=task)
    tasks_repo.save = AsyncMock()
    time_blocks_repo = MagicMock()
    time_blocks_repo.get_all_by_user = AsyncMock(return_value=[])
    time_blocks_repo.replace_focus_blocks = AsyncMock()
    user_repo = MagicMock()
    user_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(settings={}))

    monkeypatch.setattr(module, "UsersRepository", lambda db: user_repo)
    monkeypatch.setattr(module, "TasksRepository", lambda db: tasks_repo)
    monkeypatch.setattr(module, "TimeBlocksRepository", lambda db: time_blocks_repo)

    @asynccontextmanager
    async def no_transaction(db):
        yield db

    monkeypatch.setattr(module, "transaction_scope", no_transaction)

    service = SchedulerService()
    start, end = datetime(2026, 10, 7, 9, 0), datetime(2026, 10, 7, 9, 30)
    monkeypatch.setattr(
        service,
        "schedule",
        AsyncMock(
            return_value={
                "scheduledTasks": [
                    {
                        "taskId": "t1",
                        "workBlocks": [
                            {"id": "wb1", "taskId": "t1", "start": start, "end": end}
                        ],
                    }
                ]
            }
        ),
    )

    await service.run_scheduling_pipeline("u1", MagicMock(), None, emit_socket=False)

    tasks_repo.save.assert_awaited_once_with(task)
    assert task.status == "Scheduled"
    assert task.estimated_start_date == start
    assert task.updatedAt is not None
    assert task.updatedAt.tzinfo is None


@pytest.mark.anyio
async def test_scheduled_project_or_pending_task_keeps_its_status(monkeypatch):
    pending_task = SimpleNamespace(
        id="t_pending",
        projectId="proj_1",
        estimated_start_date=None,
        estimated_end_date=None,
        status="Pending",
        updatedAt=None,
        notified=True,
        lastMinuteNotified=True,
    )
    todo_project_task = SimpleNamespace(
        id="t_todo_proj",
        projectId="proj_1",
        estimated_start_date=None,
        estimated_end_date=None,
        status="Todo",
        updatedAt=None,
        notified=True,
        lastMinuteNotified=True,
    )
    by_id = {
        "t_pending": pending_task,
        "t_todo_proj": todo_project_task,
    }
    tasks_repo = MagicMock()
    tasks_repo.get_all_active_by_user = AsyncMock(return_value=[])
    tasks_repo.get_by_id = AsyncMock(side_effect=lambda tid: by_id.get(tid))
    tasks_repo.save = AsyncMock()
    time_blocks_repo = MagicMock()
    time_blocks_repo.get_all_by_user = AsyncMock(return_value=[])
    time_blocks_repo.replace_focus_blocks = AsyncMock()
    user_repo = MagicMock()
    user_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(settings={}))

    monkeypatch.setattr(module, "UsersRepository", lambda db: user_repo)
    monkeypatch.setattr(module, "TasksRepository", lambda db: tasks_repo)
    monkeypatch.setattr(module, "TimeBlocksRepository", lambda db: time_blocks_repo)

    @asynccontextmanager
    async def no_transaction(db):
        yield db

    monkeypatch.setattr(module, "transaction_scope", no_transaction)

    service = SchedulerService()
    start, end = datetime(2026, 10, 7, 9, 0), datetime(2026, 10, 7, 9, 30)
    monkeypatch.setattr(
        service,
        "schedule",
        AsyncMock(
            return_value={
                "scheduledTasks": [
                    {
                        "taskId": "t_pending",
                        "workBlocks": [
                            {"id": "wb1", "taskId": "t_pending", "start": start, "end": end}
                        ],
                    },
                    {
                        "taskId": "t_todo_proj",
                        "workBlocks": [
                            {"id": "wb2", "taskId": "t_todo_proj", "start": start, "end": end}
                        ],
                    },
                ]
            }
        ),
    )

    await service.run_scheduling_pipeline("u1", MagicMock(), None, emit_socket=False)

    assert pending_task.status == "Pending"
    assert todo_project_task.status == "Todo"

