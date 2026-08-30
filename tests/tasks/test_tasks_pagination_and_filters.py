import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.modules.task.services.tasks_service import TasksService


NOW = datetime(2026, 8, 29, 12, 0, 0)


def make_task(**overrides):
    defaults = dict(
        id="t1",
        userId="u1",
        title="Task",
        notesEncrypted="",
        estimateTimer=30,
        realTimer=0.0,
        duration=None,
        priorityLevel=2,
        category=None,
        color=None,
        estimated_start_date=None,
        estimated_end_date=None,
        deadline=NOW,
        status="Todo",
        completedAt=None,
        createdAt=NOW,
        updatedAt=NOW,
        deletedAt=None,
        tags=[],
        filters={},
        links=[],
        task_type="PlatformTask",
        google_event_id=None,
        source="platform",
        sync_status="synced",
        collaborators=[],
        time_logs=[],
        notified=False,
        lastMinuteNotified=False,
        use_ai=False,
        workspaceId=None,
        is_owner=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def service_with_tasks(tasks):
    svc = TasksService.__new__(TasksService)
    svc.db = None
    svc.google_calendar_service = None
    svc.scheduler_service = None
    svc.socket_server = None
    repo = MagicMock()
    repo.get_all_active_by_user = AsyncMock(return_value=tasks)
    svc.repository = repo
    return svc


def fifty_tasks():
    return [
        make_task(id=f"t{i}", title=f"Task {i}", priorityLevel=(i % 4) + 1)
        for i in range(50)
    ]


def test_find_all_by_user_default_limit_caps_at_24():
    svc = service_with_tasks(fifty_tasks())
    res = asyncio.run(svc.find_all_by_user("u1"))
    assert res["total"] == 50
    assert len(res["items"]) == 24


def test_paginated_query_must_return_the_requested_page_not_a_slice_of_the_first_24():
    """GraphQL getTasksByUserPaginated calls find_paginated_by_user.

    find_paginated_by_user currently calls find_all_by_user WITHOUT offset/limit
    (so the first call already caps at 24), then slices again. Asking for
    offset=24, limit=10 of 50 tasks must return items 24-33, not [].
    """
    svc = service_with_tasks(fifty_tasks())
    items, total = asyncio.run(
        svc.find_paginated_by_user("u1", offset=24, limit=10)
    )
    assert total == 50
    assert [t["id"] for t in items] == [f"t{i}" for i in range(24, 34)]


def test_paginated_limit_50_must_not_be_silently_capped_at_24():
    svc = service_with_tasks(fifty_tasks())
    items, total = asyncio.run(
        svc.find_paginated_by_user("u1", offset=0, limit=50)
    )
    assert total == 50
    assert len(items) == 50


def test_date_filter_uses_estimated_start_then_deadline():
    svc = TasksService.__new__(TasksService)
    tasks = [
        {
            "id": "with-start",
            "estimated_start_date": "2026-08-29T10:00:00",
            "deadline": "2026-09-15T10:00:00",
            "title": "A",
            "notesEncrypted": "",
        },
        {
            "id": "deadline-only",
            "estimated_start_date": None,
            "deadline": "2026-08-29T18:00:00",
            "title": "B",
            "notesEncrypted": "",
        },
        {
            "id": "next-month",
            "estimated_start_date": None,
            "deadline": "2026-09-15T10:00:00",
            "title": "C",
            "notesEncrypted": "",
        },
    ]
    filtered = svc._apply_filters_and_sorting(
        tasks,
        {
            "startDate": "2026-08-29T00:00:00.000Z",
            "endDate": "2026-08-29T23:59:59.999Z",
        },
        None,
    )
    assert {t["id"] for t in filtered} == {"with-start", "deadline-only"}


def test_search_term_matches_title_and_notes_on_full_set():
    svc = TasksService.__new__(TasksService)
    tasks = [
        {"id": "1", "title": "Write report", "notesEncrypted": ""},
        {"id": "2", "title": "Other", "notesEncrypted": "report draft"},
        {"id": "3", "title": "Unrelated", "notesEncrypted": ""},
    ]
    filtered = svc._apply_filters_and_sorting(
        tasks, {"searchTerm": "report"}, None
    )
    assert {t["id"] for t in filtered} == {"1", "2"}


def test_priority_filter_high_includes_levels_gte_3():
    svc = TasksService.__new__(TasksService)
    tasks = [
        {"id": "p1", "priorityLevel": 1, "title": "a", "notesEncrypted": ""},
        {"id": "p2", "priorityLevel": 2, "title": "b", "notesEncrypted": ""},
        {"id": "p3", "priorityLevel": 3, "title": "c", "notesEncrypted": ""},
        {"id": "p4", "priorityLevel": 4, "title": "d", "notesEncrypted": ""},
    ]
    filtered = svc._apply_filters_and_sorting(
        tasks, {"priorityLevel": [3]}, None
    )
    assert {t["id"] for t in filtered} == {"p3", "p4"}


def test_date_filter_naive_vs_aware_does_not_crash():
    svc = TasksService.__new__(TasksService)
    tasks = [
        {
            "id": "naive",
            "deadline": "2026-08-29T12:00:00",
            "title": "A",
            "notesEncrypted": "",
        }
    ]
    filtered = svc._apply_filters_and_sorting(
        tasks,
        {
            "startDate": datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc).isoformat(),
            "endDate": datetime(2026, 8, 29, 23, 59, tzinfo=timezone.utc).isoformat(),
        },
        None,
    )
    assert len(filtered) == 1
