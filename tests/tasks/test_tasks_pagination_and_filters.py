import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.modules.task.services.tasks_service import TasksService
from app.modules.task.services.tasks.tasks_filter_services import TasksFilterService



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


def test_workspace_id_filter():
    svc = TasksService.__new__(TasksService)
    svc.tasksFilter = TasksFilterService()
    tasks = [
        {"id": "t1", "workspaceId": "ws-1", "title": "A", "notesEncrypted": ""},
        {"id": "t2", "workspaceId": "ws-2", "title": "B", "notesEncrypted": ""},
        {"id": "t3", "workspaceId": None, "title": "C", "notesEncrypted": ""},
    ]
    filtered_1 = svc._apply_filters_and_sorting(
        tasks, {"workspace_id": "ws-1"}, None
    )
    assert [t["id"] for t in filtered_1] == ["t1"]

    filtered_2 = svc._apply_filters_and_sorting(
        tasks, {"workspaceId": "ws-2"}, None
    )
    assert [t["id"] for t in filtered_2] == ["t2"]


def test_map_dict_to_strawberry_task_workspace_id():
    from app.graphql.types import map_dict_to_strawberry_task

    sample_dict = {
        "id": "task-123",
        "userId": "user-1",
        "title": "Sample Task",
        "notesEncrypted": "",
        "priorityLevel": 2,
        "deadline": "2026-09-09T10:00:00",
        "status": "Todo",
        "createdAt": "2026-09-09T10:00:00",
        "updatedAt": "2026-09-09T10:00:00",
        "tags": [],
        "links": [],
        "workspaceId": "ws-abc-123",
    }
    strawberry_task = map_dict_to_strawberry_task(sample_dict)
    assert strawberry_task.workspace_id == "ws-abc-123"


def test_project_id_filter():
    svc = TasksService.__new__(TasksService)
    svc.tasksFilter = TasksFilterService()
    tasks = [
        {"id": "t1", "projectId": "proj-1", "title": "A", "notesEncrypted": ""},
        {"id": "t2", "projectId": "proj-2", "title": "B", "notesEncrypted": ""},
        {"id": "t3", "projectId": None, "title": "C", "notesEncrypted": ""},
    ]
    filtered_1 = svc._apply_filters_and_sorting(
        tasks, {"project_id": "proj-1"}, None
    )
    assert [t["id"] for t in filtered_1] == ["t1"]

    filtered_2 = svc._apply_filters_and_sorting(
        tasks, {"projectId": "proj-2"}, None
    )
    assert [t["id"] for t in filtered_2] == ["t2"]


def test_map_dict_to_strawberry_task_project_id():
    from app.graphql.types import map_dict_to_strawberry_task

    sample_dict = {
        "id": "task-123",
        "userId": "user-1",
        "title": "Sample Task",
        "notesEncrypted": "",
        "priorityLevel": 2,
        "deadline": "2026-09-09T10:00:00",
        "status": "Todo",
        "createdAt": "2026-09-09T10:00:00",
        "updatedAt": "2026-09-09T10:00:00",
        "tags": [],
        "links": [],
        "projectId": "proj-abc-123",
    }
    strawberry_task = map_dict_to_strawberry_task(sample_dict)
    assert strawberry_task.project_id == "proj-abc-123"


def test_has_project_filter():
    svc = TasksService.__new__(TasksService)
    svc.tasksFilter = TasksFilterService()
    tasks = [
        {"id": "t1", "projectId": "proj-1", "title": "A", "notesEncrypted": ""},
        {"id": "t2", "projectId": "", "title": "B", "notesEncrypted": ""},
        {"id": "t3", "projectId": None, "title": "C", "notesEncrypted": ""},
        {"id": "t4", "project_id": "proj-2", "title": "D", "notesEncrypted": ""},
    ]
    filtered = svc._apply_filters_and_sorting(
        tasks, {"has_project": True}, None
    )
    assert [t["id"] for t in filtered] == ["t1", "t4"]


def test_tasks_repository_query_tasks_direct_filters():
    from app.modules.task.infrastructure.persistence.repository import TasksRepository

    mock_db = MagicMock()
    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 42
    mock_items_res = MagicMock()
    mock_items_res.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[mock_count_res, mock_items_res])

    repo = TasksRepository(mock_db)
    items, total = asyncio.run(
        repo.query_tasks_by_user(
            user_id="user-1",
            filters={
                "status": ["Todo", "InProgress"],
                "workspace_id": "ws-1",
                "project_id": "prj-1",
                "has_project": True,
                "category": ["Work"],
            },
            sort={"sort": "deadline", "order": "desc"},
            offset=10,
            limit=20,
        )
    )

    assert total == 42
    assert items == []
    assert mock_db.execute.call_count == 2

    count_stmt = mock_db.execute.call_args_list[0][0][0]
    items_stmt = mock_db.execute.call_args_list[1][0][0]

    count_sql = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
    items_sql = str(items_stmt.compile(compile_kwargs={"literal_binds": True}))

    # Verify Base Conditions
    assert '"Task"."userId" = \'user-1\'' in items_sql
    assert '"Task"."deletedAt" IS NULL' in items_sql
    assert '"Task".source != \'google\' OR "Task".source IS NULL' in items_sql

    # Verify Direct Filters
    assert '"Task".status IN (\'Todo\', \'InProgress\')' in items_sql
    assert '"Task"."workspaceId" = \'ws-1\'' in items_sql
    assert '"Task"."projectId" = \'prj-1\'' in items_sql
    assert '"Task"."projectId" IS NOT NULL' in items_sql
    assert '"Task"."projectId" != \'\'' in items_sql
    assert 'trim("Task"."projectId") != \'\'' in items_sql
    assert '"Task".category IN (\'Work\')' in items_sql

    # Verify Sorting & Deterministic Tiebreaker
    assert 'ORDER BY "Task".deadline DESC NULLS LAST, "Task"."createdAt" DESC NULLS LAST, "Task".id ASC' in items_sql

    # Verify Pagination
    assert 'LIMIT 20' in items_sql
    assert 'OFFSET 10' in items_sql

    # Verify Count Query
    assert 'count(' in count_sql.lower()
    assert 'LIMIT' not in count_sql
    assert 'OFFSET' not in count_sql


def test_tasks_service_routes_to_sql_when_db_present():
    from app.models import Task

    mock_db = MagicMock()
    svc = TasksService.__new__(TasksService)
    svc.db = mock_db
    svc.tasksFilter = TasksFilterService()

    mock_repo = MagicMock()
    fake_task = Task(id="t1", userId="u1", title="Task 1", notesEncrypted="", status="Todo", deadline=NOW)
    mock_repo.query_tasks_by_user = AsyncMock(return_value=([fake_task], 1))
    mock_repo.get_all_active_by_user = AsyncMock(return_value=[])
    svc.repository = mock_repo

    # Case 1: Direct filters use SQL push-down
    res = asyncio.run(
        svc.find_all_by_user(
            user_id="u1",
            filters={"status": ["Todo"], "workspaceId": "ws-1"},
            offset=0,
            limit=10,
        )
    )
    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["id"] == "t1"
    mock_repo.query_tasks_by_user.assert_called_once()
    mock_repo.get_all_active_by_user.assert_not_called()

    # Case 2: When db is None, falls back to get_all_active_by_user
    svc.db = None
    mock_repo.query_tasks_by_user.reset_mock()
    mock_repo.get_all_active_by_user.reset_mock()
    res2 = asyncio.run(
        svc.find_all_by_user(
            user_id="u1",
            filters={"tags": ["urgent"]},
            offset=0,
            limit=10,
        )
    )
    mock_repo.query_tasks_by_user.assert_not_called()
    mock_repo.get_all_active_by_user.assert_called_once()


def test_tasks_service_find_paginated_by_user_routes_to_sql():
    from app.models import Task

    mock_db = MagicMock()
    svc = TasksService.__new__(TasksService)
    svc.db = mock_db
    svc.tasksFilter = TasksFilterService()

    mock_repo = MagicMock()
    fake_tasks = [
        Task(id=f"t{i}", userId="u1", title=f"Task {i}", notesEncrypted="", status="Todo", deadline=NOW)
        for i in range(5)
    ]
    mock_repo.query_tasks_by_user = AsyncMock(return_value=(fake_tasks, 25))
    svc.repository = mock_repo

    items, total = asyncio.run(
        svc.find_paginated_by_user(
            user_id="u1",
            filters={"status": ["Todo"]},
            offset=10,
            limit=5,
        )
    )
    assert total == 25
    assert len(items) == 5
    assert items[0]["id"] == "t0"
    mock_repo.query_tasks_by_user.assert_called_once_with(
        user_id="u1",
        filters={"status": ["Todo"]},
        sort=None,
        offset=10,
        limit=5,
        search="",
    )


def test_sql_pushdown_direct_filters_real_db_execution():
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.database import Base
    from app.models import Task
    from app.modules.task.infrastructure.persistence.repository import TasksRepository
    from app.modules.task.services.tasks.tasks_service import TasksService

    async def run_scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            now = datetime(2026, 9, 19, 12, 0, 0)
            tasks = [
                Task(id="t1", userId="u1", title="Task 1", notesEncrypted="", deadline=now + timedelta(days=1), status="Todo", workspaceId="ws1", projectId="p1", category="Work", createdAt=now),
                Task(id="t2", userId="u1", title="Task 2", notesEncrypted="", deadline=now + timedelta(days=2), status="Todo", workspaceId="ws1", projectId="p2", category="Work", createdAt=now - timedelta(days=1)),
                Task(id="t3", userId="u1", title="Task 3", notesEncrypted="", deadline=now + timedelta(days=3), status="Done", workspaceId="ws1", projectId="p1", category="Personal", createdAt=now - timedelta(days=2)),
                Task(id="t4", userId="u1", title="Task 4", notesEncrypted="", deadline=now + timedelta(days=4), status="Todo", workspaceId="ws2", projectId="", category="Work", createdAt=now - timedelta(days=3)),
                Task(id="t5", userId="u1", title="Task 5", notesEncrypted="", deadline=now + timedelta(days=5), status="Todo", workspaceId="ws1", projectId=None, category="Work", createdAt=now - timedelta(days=4)),
                Task(id="t6", userId="u1", title="Task 6", notesEncrypted="", deadline=now, status="Todo", workspaceId="ws1", projectId="p1", category="Work", deletedAt=now),
                Task(id="t7", userId="u1", title="Task 7", notesEncrypted="", deadline=now, status="Todo", workspaceId="ws1", projectId="p1", category="Work", source="google"),
                Task(id="t8", userId="u2", title="Task 8", notesEncrypted="", deadline=now, status="Todo", workspaceId="ws1", projectId="p1", category="Work"),
            ]
            session.add_all(tasks)
            await session.commit()

            repo = TasksRepository(session)

            # 1. Base scope: only active, non-google, u1 tasks
            items, total = await repo.query_tasks_by_user("u1")
            assert total == 5
            assert set(t.id for t in items) == {"t1", "t2", "t3", "t4", "t5"}

            # 2. Status filter
            items, total = await repo.query_tasks_by_user("u1", filters={"status": ["Todo"]})
            assert total == 4
            assert set(t.id for t in items) == {"t1", "t2", "t4", "t5"}

            # 3. Workspace filter
            items, total = await repo.query_tasks_by_user("u1", filters={"workspace_id": "ws1"})
            assert total == 4
            assert set(t.id for t in items) == {"t1", "t2", "t3", "t5"}

            # 4. Has project filter (requires non-null and non-empty projectId)
            items, total = await repo.query_tasks_by_user("u1", filters={"has_project": True})
            assert total == 3
            assert set(t.id for t in items) == {"t1", "t2", "t3"}

            # 5. Combined filters + sorting with tiebreaker
            items, total = await repo.query_tasks_by_user(
                "u1",
                filters={"status": ["Todo"], "workspaceId": "ws1", "has_project": True, "category": ["Work"]},
                sort={"sort": "deadline", "order": "desc"},
            )
            assert total == 2
            assert [t.id for t in items] == ["t2", "t1"]

            # 6. Pagination on real DB (Page 1 vs Page 2)
            p1, tot1 = await repo.query_tasks_by_user(
                "u1",
                filters={"status": ["Todo"], "workspaceId": "ws1", "has_project": True, "category": ["Work"]},
                sort={"sort": "deadline", "order": "desc"},
                offset=0,
                limit=1,
            )
            assert tot1 == 2
            assert [t.id for t in p1] == ["t2"]

            p2, tot2 = await repo.query_tasks_by_user(
                "u1",
                filters={"status": ["Todo"], "workspaceId": "ws1", "has_project": True, "category": ["Work"]},
                sort={"sort": "deadline", "order": "desc"},
                offset=1,
                limit=1,
            )
            assert tot2 == 2
            assert [t.id for t in p2] == ["t1"]

            # 7. End-to-end via TasksService.find_paginated_by_user
            svc = TasksService(session)
            service_items, service_total = await svc.find_paginated_by_user(
                "u1",
                filters={"status": ["Todo"], "workspaceId": "ws1", "has_project": True, "category": ["Work"]},
                sort={"sort": "deadline", "order": "desc"},
                offset=0,
                limit=1,
            )
            assert service_total == 2
            assert len(service_items) == 1
            assert service_items[0]["id"] == "t2"

    asyncio.run(run_scenario())


def test_tasks_repository_query_tasks_fase_2_filters():
    from app.modules.task.infrastructure.persistence.repository import TasksRepository
    from sqlalchemy.dialects import postgresql

    mock_db = MagicMock()
    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 5
    mock_items_res = MagicMock()
    mock_items_res.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[mock_count_res, mock_items_res, mock_count_res, mock_items_res])

    repo = TasksRepository(mock_db)

    # 1. priorityLevel >= 3 logic
    asyncio.run(
        repo.query_tasks_by_user(
            user_id="user-1",
            filters={"priorityLevel": [3]},
            search="revisión",
        )
    )
    items_stmt = mock_db.execute.call_args_list[1][0][0]
    items_sql = str(items_stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert '"Task"."priorityLevel" >= 3 OR "Task"."priorityLevel" IN (3)' in items_sql
    assert '"Task".title ILIKE \'%%revisión%%\'' in items_sql

    # 2. priorityLevel < 3 and searchTerm across title and notesEncrypted (plain text)
    asyncio.run(
        repo.query_tasks_by_user(
            user_id="user-1",
            filters={"priorityLevel": [1, 2], "searchTerm": "diseño"},
        )
    )
    items_stmt_2 = mock_db.execute.call_args_list[3][0][0]
    items_sql_2 = str(items_stmt_2.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert '"Task"."priorityLevel" IN (1, 2)' in items_sql_2
    assert '"Task"."priorityLevel" >= 3' not in items_sql_2
    assert '"Task".title ILIKE \'%%diseño%%\' OR "Task"."notesEncrypted" ILIKE \'%%diseño%%\'' in items_sql_2


def test_sql_pushdown_fase_2_real_db_execution():
    """Validates Fase 2 filters (priorityLevel >= 3, search, searchTerm on plain text notes)
    in a real database, including Unicode accent handling (matching vs non-matching).
    """
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import event
    from app.database import Base
    from app.models import Task
    from app.modules.task.infrastructure.persistence.repository import TasksRepository

    async def run_scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        # Register Python Unicode lower on SQLite connection so non-ASCII case-folding matches Postgres UTF-8
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_unicode_lower(dbapi_connection, connection_record):
            dbapi_connection.create_function("lower", 1, lambda s: s.lower() if s is not None else None)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            now = datetime(2026, 9, 19, 12, 0, 0)
            tasks = [
                Task(id="p1", userId="u1", title="Baja prioridad", notesEncrypted="", deadline=now, priorityLevel=1, status="Todo"),
                Task(id="p2", userId="u1", title="Media prioridad", notesEncrypted="", deadline=now, priorityLevel=2, status="Todo"),
                Task(id="p3", userId="u1", title="Alta prioridad", notesEncrypted="", deadline=now, priorityLevel=3, status="Todo"),
                Task(id="p4", userId="u1", title="Urgente prioridad", notesEncrypted="", deadline=now, priorityLevel=4, status="Todo"),
                Task(id="s1", userId="u1", title="Revisión de arquitectura", notesEncrypted="Todo listo", deadline=now, priorityLevel=2, status="Todo"),
                Task(id="s2", userId="u1", title="Diseño de UI", notesEncrypted="Notas estándar", deadline=now, priorityLevel=2, status="Todo"),
                Task(id="s3", userId="u1", title="Seguridad web", notesEncrypted="Revisión de notas de diseño detalladas", deadline=now, priorityLevel=2, status="Todo"),
                Task(id="s4", userId="u1", title="Café con el equipo", notesEncrypted="Hablar de CAFÉ y galletas", deadline=now, priorityLevel=2, status="Todo"),
            ]
            session.add_all(tasks)
            await session.commit()

            repo = TasksRepository(session)

            # 1. priorityLevel: [1] -> only p1
            items, total = await repo.query_tasks_by_user("u1", filters={"priorityLevel": [1]})
            assert total == 1
            assert [t.id for t in items] == ["p1"]

            # 2. priorityLevel >= 3 rule: [3] should include both priority 3 and priority 4
            items, total = await repo.query_tasks_by_user("u1", filters={"priorityLevel": [3]})
            assert total == 2
            assert set(t.id for t in items) == {"p3", "p4"}

            # 3. search on title (case-insensitive with accent 'revisión')
            items, total = await repo.query_tasks_by_user("u1", search="revisión")
            assert total == 1
            assert items[0].id == "s1"

            # 4. searchTerm in notesEncrypted (plain text search)
            items, total = await repo.query_tasks_by_user("u1", filters={"searchTerm": "arquitectura"})
            assert total == 1
            assert items[0].id == "s1"

            # 5. Accent test 1: searchTerm="diseño" matches title of s2 and notes of s3
            items, total = await repo.query_tasks_by_user("u1", filters={"searchTerm": "diseño"})
            assert total == 2
            assert set(t.id for t in items) == {"s2", "s3"}

            # 6. Accent test 2: case-insensitive uppercase/lowercase with accent ("café" vs "CAFÉ")
            items, total = await repo.query_tasks_by_user("u1", filters={"searchTerm": "café"})
            assert total == 1
            assert items[0].id == "s4"

            # 7. Accent test 3: searching without accent "diseno" does NOT match "diseño"
            # (Neither Postgres ILIKE nor Python in-memory strips accents without unaccent extension)
            items, total = await repo.query_tasks_by_user("u1", filters={"searchTerm": "diseno"})
            assert total == 0

    asyncio.run(run_scenario())


def test_tasks_service_fase_2_routing():
    from app.models import Task

    mock_db = MagicMock()
    svc = TasksService.__new__(TasksService)
    svc.db = mock_db
    svc.tasksFilter = TasksFilterService()

    mock_repo = MagicMock()
    fake_task = Task(id="t1", userId="u1", title="Task 1", notesEncrypted="", status="Todo", deadline=NOW)
    mock_repo.query_tasks_by_user = AsyncMock(return_value=([fake_task], 1))
    mock_repo.get_all_active_by_user = AsyncMock(return_value=[])
    svc.repository = mock_repo

    # Case 1: Fase 2 filters (priorityLevel, search, searchTerm) route to SQL
    res = asyncio.run(
        svc.find_all_by_user(
            user_id="u1",
            filters={"priorityLevel": [3], "searchTerm": "diseño"},
            search="UI",
            offset=0,
            limit=10,
        )
    )
    assert res["total"] == 1
    mock_repo.query_tasks_by_user.assert_called_once()
    mock_repo.get_all_active_by_user.assert_not_called()

    # Case 2: When db is None, falls back to get_all_active_by_user
    svc.db = None
    mock_repo.query_tasks_by_user.reset_mock()
    mock_repo.get_all_active_by_user.reset_mock()
    res2 = asyncio.run(
        svc.find_all_by_user(
            user_id="u1",
            filters={"priorityLevel": [3], "tags": ["frontend"]},
            offset=0,
            limit=10,
        )
    )
    mock_repo.query_tasks_by_user.assert_not_called()
    mock_repo.get_all_active_by_user.assert_called_once()


def test_tasks_repository_query_tasks_fase_3_dates_compilation():
    from app.modules.task.infrastructure.persistence.repository import TasksRepository
    from sqlalchemy.dialects import postgresql

    mock_db = MagicMock()
    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 2
    mock_items_res = MagicMock()
    mock_items_res.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[mock_count_res, mock_items_res])

    repo = TasksRepository(mock_db)
    asyncio.run(
        repo.query_tasks_by_user(
            user_id="user-1",
            filters={
                "startDate": "2026-08-01T00:00:00Z",
                "endDate": "2026-08-31T23:59:59Z",
            },
        )
    )

    items_stmt = mock_db.execute.call_args_list[1][0][0]
    items_sql = str(items_stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert 'coalesce("Task".estimated_start_date, "Task".deadline, "Task"."completedAt", "Task"."createdAt") >=' in items_sql
    assert 'coalesce("Task".estimated_start_date, "Task".deadline, "Task"."completedAt", "Task"."createdAt") <=' in items_sql
    assert "'2026-08-01 00:00:00'" in items_sql
    assert "'2026-08-31 23:59:59'" in items_sql


def test_sql_pushdown_fase_3_real_db_execution():
    """Validates Fase 3 date filters with COALESCE fallback chain and timezone normalization
    in a real database execution.
    """
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.database import Base
    from app.models import Task
    from app.modules.task.infrastructure.persistence.repository import TasksRepository
    from app.modules.task.services.tasks.tasks_service import TasksService

    async def run_scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            t_base = datetime(2026, 8, 15, 12, 0, 0)
            tasks = [
                # 1. Has estimated_start_date on Aug 10 (inside range Aug 8 - Aug 22, even though deadline is Sep 5)
                Task(
                    id="d1",
                    userId="u1",
                    title="Task with estimated start",
                    notesEncrypted="",
                    estimated_start_date=t_base - timedelta(days=5),
                    deadline=t_base + timedelta(days=21),
                    status="Todo",
                ),
                # 2. No estimated_start_date, deadline on Aug 18 (inside range via fallback)
                Task(
                    id="d2",
                    userId="u1",
                    title="Task with deadline fallback",
                    notesEncrypted="",
                    estimated_start_date=None,
                    deadline=t_base + timedelta(days=3),
                    status="Todo",
                ),
                # 3. No estimated_start_date, deadline on Aug 30 (outside range)
                Task(
                    id="d3",
                    userId="u1",
                    title="Task outside range",
                    notesEncrypted="",
                    estimated_start_date=None,
                    deadline=t_base + timedelta(days=15),
                    status="Todo",
                ),
            ]
            session.add_all(tasks)
            await session.commit()

            repo = TasksRepository(session)

            # Test 1: Date range using UTC ISO string with 'Z'
            items, total = await repo.query_tasks_by_user(
                "u1",
                filters={
                    "startDate": "2026-08-08T00:00:00Z",
                    "endDate": "2026-08-22T00:00:00Z",
                },
            )
            assert total == 2
            assert set(t.id for t in items) == {"d1", "d2"}

            # Test 2: Date range with timezone offset (+05:00) normalized to UTC
            # 2026-08-08T05:00:00+05:00 == 2026-08-08T00:00:00Z
            items, total = await repo.query_tasks_by_user(
                "u1",
                filters={
                    "startDate": "2026-08-08T05:00:00+05:00",
                    "endDate": "2026-08-22T05:00:00+05:00",
                },
            )
            assert total == 2
            assert set(t.id for t in items) == {"d1", "d2"}

            # Test 3: Only startDate
            items, total = await repo.query_tasks_by_user(
                "u1",
                filters={"startDate": "2026-08-15T00:00:00Z"},
            )
            assert total == 2
            assert set(t.id for t in items) == {"d2", "d3"}

            # Test 4: Only endDate
            items, total = await repo.query_tasks_by_user(
                "u1",
                filters={"endDate": "2026-08-15T00:00:00Z"},
            )
            assert total == 1
            assert items[0].id == "d1"

            # Test 5: End-to-end via TasksService.find_paginated_by_user
            svc = TasksService(session)
            items_svc, total_svc = await svc.find_paginated_by_user(
                "u1",
                filters={
                    "startDate": "2026-08-08T00:00:00Z",
                    "endDate": "2026-08-22T00:00:00Z",
                },
                offset=0,
                limit=10,
            )
            assert total_svc == 2
            assert len(items_svc) == 2
            assert set(t["id"] for t in items_svc) == {"d1", "d2"}

    asyncio.run(run_scenario())


def test_tasks_service_fase_3_routing():
    from app.models import Task

    mock_db = MagicMock()
    svc = TasksService.__new__(TasksService)
    svc.db = mock_db
    svc.tasksFilter = TasksFilterService()

    mock_repo = MagicMock()
    fake_task = Task(id="t1", userId="u1", title="Task 1", notesEncrypted="", status="Todo", deadline=NOW)
    mock_repo.query_tasks_by_user = AsyncMock(return_value=([fake_task], 1))
    mock_repo.get_all_active_by_user = AsyncMock(return_value=[])
    svc.repository = mock_repo

    # Case 1: Date filters route to SQL pushdown
    res = asyncio.run(
        svc.find_all_by_user(
            user_id="u1",
            filters={
                "status": ["Todo"],
                "startDate": "2026-08-01T00:00:00Z",
                "endDate": "2026-08-31T23:59:59Z",
            },
            offset=0,
            limit=10,
        )
    )
    assert res["total"] == 1
    mock_repo.query_tasks_by_user.assert_called_once()
    mock_repo.get_all_active_by_user.assert_not_called()

    # Case 2: When db is None, falls back to memory pipeline
    svc.db = None
    mock_repo.query_tasks_by_user.reset_mock()
    mock_repo.get_all_active_by_user.reset_mock()
    mock_repo.get_all_active_by_user.return_value = []
    res2 = asyncio.run(
        svc.find_all_by_user(
            user_id="u1",
            filters={"tags": ["urgent"]},
            offset=0,
            limit=10,
        )
    )
    mock_repo.query_tasks_by_user.assert_not_called()
    mock_repo.get_all_active_by_user.assert_called_once()


def test_parse_filter_date_naive_and_aware_parity():
    """Confirms parse_filter_date parity with original tasks_filter_services.py:
    Naive date strings (without Z or offset) are treated directly as UTC,
    identical to original replace(tzinfo=timezone.utc), avoiding local time shifts.
    """
    from app.modules.task.infrastructure.persistence.repository import parse_filter_date

    # 1. ISO string with Z
    res_z = parse_filter_date("2026-08-15T12:00:00Z")
    assert res_z == datetime(2026, 8, 15, 12, 0, 0)
    assert res_z.tzinfo is None

    # 2. ISO string with offset (+05:00) -> converts 17:00 +05:00 to 12:00 UTC
    res_offset = parse_filter_date("2026-08-15T17:00:00+05:00")
    assert res_offset == datetime(2026, 8, 15, 12, 0, 0)
    assert res_offset.tzinfo is None

    # 3. Naive ISO string (without Z or offset) -> treated directly as UTC
    res_naive = parse_filter_date("2026-08-15T12:00:00")
    assert res_naive == datetime(2026, 8, 15, 12, 0, 0)
    assert res_naive.tzinfo is None

    # 4. Aware datetime object -> converts to naive UTC
    res_dt_aware = parse_filter_date(datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc))
    assert res_dt_aware == datetime(2026, 8, 15, 12, 0, 0)
    assert res_dt_aware.tzinfo is None

    # 5. Naive datetime object -> treated directly as UTC
    res_dt_naive = parse_filter_date(datetime(2026, 8, 15, 12, 0, 0))
    assert res_dt_naive == datetime(2026, 8, 15, 12, 0, 0)
    assert res_dt_naive.tzinfo is None


def test_sql_pushdown_tags_option_b_pagination():
    """Validates Opción B for tags: SQL pre-filters all non-tag criteria,
    Python evaluates tags and computes exact totalCount, slicing pages in memory.
    """
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.database import Base
    from app.models import Task
    from app.modules.task.infrastructure.persistence.repository import TasksRepository

    async def run_scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            now = datetime(2026, 9, 19, 12, 0, 0)
            # Create 6 tasks: 4 with tag 'frontend', 2 with tag 'backend'
            # With status 'Todo', and ordered by createdAt
            tasks = [
                Task(id=f"t{i}", userId="u1", title=f"Task {i}", notesEncrypted="", deadline=now, status="Todo", tags=["frontend"] if i < 4 else ["backend"], createdAt=now - timedelta(minutes=i))
                for i in range(6)
            ]
            session.add_all(tasks)
            await session.commit()

            repo = TasksRepository(session)

            # Query Page 1: limit 2, offset 0 with tag 'frontend'
            p1_items, p1_total = await repo.query_tasks_by_user(
                "u1",
                filters={"status": ["Todo"], "tags": ["frontend"]},
                offset=0,
                limit=2,
            )
            assert p1_total == 4
            assert len(p1_items) == 2
            assert [t.id for t in p1_items] == ["t0", "t1"]

            # Query Page 2: limit 2, offset 2 with tag 'frontend'
            p2_items, p2_total = await repo.query_tasks_by_user(
                "u1",
                filters={"status": ["Todo"], "tags": ["frontend"]},
                offset=2,
                limit=2,
            )
            assert p2_total == 4
            assert len(p2_items) == 2
            assert [t.id for t in p2_items] == ["t2", "t3"]

        await engine.dispose()

    asyncio.run(run_scenario())


def test_sql_pushdown_tags_option_b_determinism():
    """Validates determinism for tags pagination (Opción B):
    Executing the exact same paginated query with tags multiple times
    returns identical tasks in identical order with identical totalCount.
    """
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.database import Base
    from app.models import Task
    from app.modules.task.infrastructure.persistence.repository import TasksRepository

    async def run_scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            now = datetime(2026, 9, 19, 12, 0, 0)
            # Heterogeneous tag structures (string vs dict)
            tasks = [
                Task(id="tg-1", userId="u1", title="Task 1", notesEncrypted="", deadline=now, status="Todo", tags=["frontend", "bug"], createdAt=now),
                Task(id="tg-2", userId="u1", title="Task 2", notesEncrypted="", deadline=now, status="Todo", tags=[{"name": "frontend"}], createdAt=now - timedelta(hours=1)),
                Task(id="tg-3", userId="u1", title="Task 3", notesEncrypted="", deadline=now, status="Todo", tags=["frontend"], createdAt=now - timedelta(hours=2)),
                Task(id="tg-4", userId="u1", title="Task 4", notesEncrypted="", deadline=now, status="Todo", tags=[{"name": "FRONTEND"}], createdAt=now - timedelta(hours=3)),
                Task(id="tg-5", userId="u1", title="Task 5", notesEncrypted="", deadline=now, status="Todo", tags=["backend"], createdAt=now - timedelta(hours=4)),
            ]
            session.add_all(tasks)
            await session.commit()

            repo = TasksRepository(session)

            # Execution 1 of Page 1
            run1_items_p1, run1_tot_p1 = await repo.query_tasks_by_user("u1", filters={"tags": ["frontend"]}, offset=0, limit=2)
            # Execution 2 of Page 1
            run2_items_p1, run2_tot_p1 = await repo.query_tasks_by_user("u1", filters={"tags": ["frontend"]}, offset=0, limit=2)

            # Determinism Assertion: identical IDs, identical order, identical total
            assert run1_tot_p1 == 4
            assert run2_tot_p1 == 4
            assert [t.id for t in run1_items_p1] == ["tg-1", "tg-2"]
            assert [t.id for t in run1_items_p1] == [t.id for t in run2_items_p1]

            # Execution 1 of Page 2
            run1_items_p2, run1_tot_p2 = await repo.query_tasks_by_user("u1", filters={"tags": ["frontend"]}, offset=2, limit=2)
            # Execution 2 of Page 2
            run2_items_p2, run2_tot_p2 = await repo.query_tasks_by_user("u1", filters={"tags": ["frontend"]}, offset=2, limit=2)

            # Determinism Assertion Page 2
            assert run1_tot_p2 == 4
            assert run2_tot_p2 == 4
            assert [t.id for t in run1_items_p2] == ["tg-3", "tg-4"]
            assert [t.id for t in run1_items_p2] == [t.id for t in run2_items_p2]

            # Cross-page non-overlap check
            page1_ids = set(t.id for t in run1_items_p1)
            page2_ids = set(t.id for t in run1_items_p2)
            assert page1_ids.isdisjoint(page2_ids)

        await engine.dispose()

    asyncio.run(run_scenario())


def test_tags_filter_parity_orm_vs_dict_and_multi_tags():
    """Confirms 100% parity between TasksFilterService.filter_tags_only on dicts,
    TasksFilterService.filter_tags_only on Task ORM objects, and query_tasks_by_user in SQL.
    Validates:
    1. Case-insensitivity (['FRONTEND'] matches 'frontend' and {'name': 'Frontend'})
    2. Multiple tags semantics (OR behavior: matching any of the tags in filters['tags'])
    3. Dict vs string format support
    4. Non-matching tags exclusion
    """
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.database import Base
    from app.models import Task
    from app.modules.task.infrastructure.persistence.repository import TasksRepository
    from app.modules.task.services.tasks.tasks_filter_services import TasksFilterService
    from app.modules.task.services.tasks.tasks_mapper import task_to_dict

    now = datetime(2026, 9, 21, 10, 0, 0)
    orm_tasks = [
        Task(id="t1", userId="u1", title="T1", notesEncrypted="", deadline=now, status="Todo", tags=["frontend", "react"], createdAt=now),
        Task(id="t2", userId="u1", title="T2", notesEncrypted="", deadline=now, status="Todo", tags=[{"name": "Frontend"}], createdAt=now - timedelta(minutes=1)),
        Task(id="t3", userId="u1", title="T3", notesEncrypted="", deadline=now, status="Todo", tags=["backend", "python"], createdAt=now - timedelta(minutes=2)),
        Task(id="t4", userId="u1", title="T4", notesEncrypted="", deadline=now, status="Todo", tags=[{"name": "BACKEND"}], createdAt=now - timedelta(minutes=3)),
        Task(id="t5", userId="u1", title="T5", notesEncrypted="", deadline=now, status="Todo", tags=["frontend", "backend"], createdAt=now - timedelta(minutes=4)),
        Task(id="t6", userId="u1", title="T6", notesEncrypted="", deadline=now, status="Todo", tags=["devops"], createdAt=now - timedelta(minutes=5)),
        Task(id="t7", userId="u1", title="T7", notesEncrypted="", deadline=now, status="Todo", tags=[], createdAt=now - timedelta(minutes=6)),
    ]
    dict_tasks = [task_to_dict(t) for t in orm_tasks]

    # Test Case 1: Single tag case-insensitive
    res_dict_1 = TasksFilterService.filter_tags_only(dict_tasks, ["FRONTEND"])
    res_orm_1 = TasksFilterService.filter_tags_only(orm_tasks, ["FRONTEND"])
    expected_ids_1 = ["t1", "t2", "t5"]
    assert [t["id"] for t in res_dict_1] == expected_ids_1
    assert [t.id for t in res_orm_1] == expected_ids_1

    # Test Case 2: Multiple tags OR semantics
    res_dict_multi = TasksFilterService.filter_tags_only(dict_tasks, ["frontend", "backend"])
    res_orm_multi = TasksFilterService.filter_tags_only(orm_tasks, ["frontend", "backend"])
    expected_ids_multi = ["t1", "t2", "t3", "t4", "t5"]
    assert [t["id"] for t in res_dict_multi] == expected_ids_multi
    assert [t.id for t in res_orm_multi] == expected_ids_multi

    # Test Case 3: Tag that matches nothing
    res_dict_none = TasksFilterService.filter_tags_only(dict_tasks, ["nonexistent"])
    res_orm_none = TasksFilterService.filter_tags_only(orm_tasks, ["nonexistent"])
    assert res_dict_none == []
    assert res_orm_none == []

    # Test Case 4: Real DB execution via query_tasks_by_user
    async def run_db():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            session.add_all(orm_tasks)
            await session.commit()

            repo = TasksRepository(session)
            items_db, total_db = await repo.query_tasks_by_user(
                "u1",
                filters={"tags": ["frontend", "backend"]},
                offset=0,
                limit=10,
            )
            assert total_db == 5
            assert [t.id for t in items_db] == expected_ids_multi

        await engine.dispose()

    asyncio.run(run_db())











