from datetime import datetime, timedelta
import pytest
from app.modules.task.services.scheduler_service import SchedulerService


@pytest.mark.anyio
async def test_schedule_single_task_success():
    scheduler = SchedulerService()
    now = datetime.now()
    deadline = now + timedelta(days=2)

    tasks = [
        {
            "id": "task_1",
            "userId": "user_123",
            "title": "Estudiar DDD y Clean Architecture",
            "estimateTimer": 60,
            "realTimer": 0,
            "duration": None,
            "priorityValue": 1,
            "category": "Estudio",
            "color": "#4A90E2",
            "estimated_start_date": None,
            "estimated_end_date": None,
            "deadline": deadline,
            "status": "Todo",
            "tags": [],
            "links": [],
            "collaborators": [],
            "use_ai": False,
        }
    ]

    constraints = {
        "userId": "user_123",
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

    res = await scheduler.schedule(
        user_id="user_123",
        external_events=[],
        meetings=[],
        tasks=tasks,
        constraints=constraints,
        existing_work_blocks=[],
    )

    assert "scheduledTasks" in res
    assert "unscheduledTasks" in res
    assert len(res["scheduledTasks"]) == 1
    assert res["scheduledTasks"][0]["taskId"] == "task_1"
    assert res["scheduledTasks"][0]["status"] == "scheduled"
    assert len(res["scheduledTasks"][0]["workBlocks"]) > 0


@pytest.mark.anyio
async def test_schedule_task_avoids_existing_meeting():
    scheduler = SchedulerService()
    now = datetime.now()
    deadline = now + timedelta(days=1)

    tasks = [
        {
            "id": "task_2",
            "userId": "user_123",
            "title": "Preparar demo de Focusly",
            "estimateTimer": 60,
            "realTimer": 0,
            "duration": None,
            "priorityValue": 2,
            "category": "Trabajo",
            "color": "#E91E63",
            "estimated_start_date": None,
            "estimated_end_date": None,
            "deadline": deadline,
            "status": "Todo",
            "tags": [],
            "links": [],
            "collaborators": [],
            "use_ai": False,
        }
    ]

    meeting_start = now + timedelta(hours=1)
    meeting_end = now + timedelta(hours=2)

    meetings = [
        {
            "id": "meeting_1",
            "title": "Reunión de Equipo",
            "start": meeting_start,
            "end": meeting_end,
        }
    ]

    constraints = {
        "userId": "user_123",
        "workingDays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "workingHours": {"start": "00:00", "end": "23:59"},
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

    res = await scheduler.schedule(
        user_id="user_123",
        external_events=[],
        meetings=meetings,
        tasks=tasks,
        constraints=constraints,
        existing_work_blocks=[],
    )

    assert len(res["scheduledTasks"]) == 1
    scheduled_block = res["scheduledTasks"][0]["workBlocks"][0]
    assert (
        scheduled_block["start"] >= meeting_end
        or scheduled_block["end"] <= meeting_start
    )
