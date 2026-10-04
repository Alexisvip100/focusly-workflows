"""Tasks without a date (NULL deadline) flow through scheduling, the GraphQL
type and Google Calendar mirroring without breaking or being invented a date."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.graphql import types
from app.modules.task.services.migration_service import MigrationService
from app.modules.task.services.scheduler_service import SchedulerService
from app.modules.task.services.tasks.tasks_sync_service import TasksSyncService

CONSTRAINTS = {
    "userId": "user_1",
    "workingDays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "workingHours": {"start": "08:00", "end": "20:00"},
    "breakDuration": 15,
    "breakInterval": 90,
    "preferredFocusBlockDuration": 60,
    "minFocusBlockDuration": 30,
    "maxFocusBlockDuration": 120,
    "schedulingStrategy": "balanced",
    "allowSameDaySplitting": True,
    "allowOvertime": False,
    "goldenWindow": {"start": "09:00", "end": "11:00"},
}


def raw_task(task_id, deadline):
    return {
        "id": task_id,
        "userId": "user_1",
        "title": task_id,
        "estimateTimer": 60,
        "realTimer": 0,
        "duration": None,
        "priorityValue": 2,
        "category": None,
        "color": None,
        "estimated_start_date": None,
        "estimated_end_date": None,
        "deadline": deadline,
        "status": "Todo",
        "tags": [],
        "links": [],
        "collaborators": [],
        "use_ai": False,
    }


@pytest.mark.anyio
async def test_scheduler_handles_undated_tasks_after_dated_ones():
    migrator = MigrationService()
    tasks = [
        migrator.migrate_task(raw_task("undated", None))["task"],
        migrator.migrate_task(
            raw_task("dated", datetime.now() + timedelta(days=1))
        )["task"],
    ]

    res = await SchedulerService().schedule(
        user_id="user_1",
        external_events=[],
        meetings=[],
        tasks=tasks,
        constraints=CONSTRAINTS,
        existing_work_blocks=[],
    )

    scheduled = [t["taskId"] for t in res["scheduledTasks"]]
    assert set(scheduled) == {"undated", "dated"}
    # With equal priority the task that has a date goes first.
    assert scheduled.index("dated") < scheduled.index("undated")


def test_graphql_task_keeps_a_missing_deadline_null():
    task = types.map_dict_to_strawberry_task(
        {
            "id": "task-1",
            "userId": "owner",
            "title": "Sin fecha",
            "notes": "",
            "priorityLevel": 2,
            "status": "Todo",
            "deadline": None,
        }
    )

    assert task.deadline is None


@pytest.mark.anyio
async def test_undated_new_task_is_not_mirrored_to_google():
    google = MagicMock()
    google.create_event = AsyncMock()
    sync = TasksSyncService(MagicMock(), google_calendar_service=google)

    with patch(
        "app.modules.task.services.tasks.tasks_sync_service.UsersRepository"
    ) as users:
        await sync.sync_create_to_google(
            "user_1", {"title": "Sin fecha", "deadline": None}
        )

    users.assert_not_called()
    google.create_event.assert_not_called()


@pytest.mark.anyio
async def test_removing_a_mirrored_tasks_dates_leaves_its_event_alone():
    google = MagicMock()
    google.patch_event = AsyncMock()
    sync = TasksSyncService(MagicMock(), google_calendar_service=google)
    task = SimpleNamespace(
        id="task-1",
        userId="user_1",
        google_event_id="evt-1",
        task_type="GoogleTask",
    )

    with patch(
        "app.modules.task.services.tasks.tasks_sync_service.task_to_dict",
        return_value={"id": "task-1", "deadline": None, "estimated_start_date": None},
    ):
        await sync.sync_update_to_google(task)

    google.patch_event.assert_not_called()
