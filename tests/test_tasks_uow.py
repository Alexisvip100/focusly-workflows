import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

from app.database import transaction_scope
from app.models import Task
from app.modules.task.services.tasks.tasks_service import TasksService


def make_mock_db():
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)

    # Mock transaction context manager
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    db.begin = MagicMock(return_value=tx)

    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.merge = AsyncMock(side_effect=lambda x: x)
    return db, tx


@pytest.mark.anyio
async def test_tasks_service_create_rolls_back_if_scheduler_fails():
    """Test 1: If scheduler pipeline raises an exception during task creation,
    the transaction rolls back and the exception is propagated."""
    db, tx = make_mock_db()
    
    tasks_service = TasksService(db=db)
    tasks_service.repository = MagicMock()
    tasks_service.repository.create = AsyncMock()
    tasks_service.repository.get_by_google_event_id = AsyncMock(return_value=None)
    
    # Mock scheduler failure
    tasks_service.sync_service = MagicMock()
    tasks_service.sync_service.sync_create_to_google = AsyncMock()
    tasks_service.sync_service.trigger_scheduler_pipeline = AsyncMock(
        side_effect=RuntimeError("Scheduler engine crash")
    )
    tasks_service.sync_service.emit_schedule_updated = AsyncMock()

    task_payload = {
        "userId": "user-1",
        "title": "Unfinished task",
        "status": "Todo",
    }

    with pytest.raises(RuntimeError, match="Scheduler engine crash"):
        await tasks_service.create(task_payload)

    # Repository was called to stage the task
    tasks_service.repository.create.assert_called_once()
    # Transaction context manager exited with error -> rollback occurred in transaction_scope
    tx.__aexit__.assert_called_once()
    exc_type = tx.__aexit__.call_args[0][0]
    assert exc_type is RuntimeError

    # Socket event MUST NOT be emitted because transaction failed
    tasks_service.sync_service.emit_schedule_updated.assert_not_called()


@pytest.mark.anyio
async def test_tasks_service_create_compensates_google_event_on_db_failure():
    """Test 2: If Google event is created but the DB transaction subsequently fails,
    delete_event is called as a compensating action to avoid orphaned Google events."""
    db, tx = make_mock_db()
    
    google_cal_service = MagicMock()
    google_cal_service.delete_event = AsyncMock()

    tasks_service = TasksService(db=db, google_calendar_service=google_cal_service)
    tasks_service.repository = MagicMock()
    tasks_service.repository.get_by_google_event_id = AsyncMock(return_value=None)
    # DB insert fails
    tasks_service.repository.create = AsyncMock(side_effect=ValueError("DB constraint error"))

    tasks_service.sync_service = MagicMock()
    # Simulate Google creating an event id
    async def fake_sync_google(uid, data):
        data["google_event_id"] = "g-event-123"
        data["task_type"] = "GoogleTask"
    tasks_service.sync_service.sync_create_to_google = AsyncMock(side_effect=fake_sync_google)
    tasks_service.sync_service.emit_schedule_updated = AsyncMock()

    task_payload = {
        "userId": "user-1",
        "title": "Google sync task",
        "status": "Todo",
    }

    with pytest.raises(ValueError, match="DB constraint error"):
        await tasks_service.create(task_payload)

    # Verify compensating delete was called with the created google event id
    google_cal_service.delete_event.assert_called_once_with("user-1", "g-event-123")
    tasks_service.sync_service.emit_schedule_updated.assert_not_called()


@pytest.mark.anyio
async def test_tasks_service_create_commits_and_emits_socket_on_success():
    """Test 3: When creation succeeds, transaction commits cleanly and Socket.IO
    is emitted strictly after the transaction commit."""
    db, tx = make_mock_db()

    tasks_service = TasksService(db=db)
    tasks_service.repository = MagicMock()
    tasks_service.repository.get_by_google_event_id = AsyncMock(return_value=None)
    tasks_service.repository.create = AsyncMock()

    tasks_service.sync_service = MagicMock()
    tasks_service.sync_service.sync_create_to_google = AsyncMock()
    tasks_service.sync_service.trigger_scheduler_pipeline = AsyncMock()
    tasks_service.sync_service.emit_schedule_updated = AsyncMock()

    task_payload = {
        "userId": "user-1",
        "title": "Successful task",
        "status": "Todo",
    }

    result = await tasks_service.create(task_payload)

    assert result["title"] == "Successful task"
    # Scheduler called without emitting socket inside transaction
    tasks_service.sync_service.trigger_scheduler_pipeline.assert_called_once_with("user-1", emit_socket=False)
    # Context manager exited cleanly (no exception)
    tx.__aexit__.assert_called_once_with(None, None, None)
    # Socket emitted post-commit
    tasks_service.sync_service.emit_schedule_updated.assert_called_once_with("user-1")


@pytest.mark.anyio
async def test_transaction_scope_nested_uses_begin_nested():
    """Test 4: transaction_scope uses savepoint (begin_nested) when already in a transaction."""
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=True)

    nested_tx = MagicMock()
    nested_tx.__aenter__ = AsyncMock(return_value=nested_tx)
    nested_tx.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_tx)

    async with transaction_scope(db):
        pass

    db.begin_nested.assert_called_once()
    nested_tx.__aenter__.assert_called_once()
    nested_tx.__aexit__.assert_called_once_with(None, None, None)
