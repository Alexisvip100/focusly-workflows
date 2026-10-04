"""Task creation without a date, unlinking through updateTask, and searching
tasks by tag or project name."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.future import select

from app.graphql import schema
from app.models import Task
from app.modules.task.infrastructure.persistence.repository import (
    search_term_condition,
)
from app.modules.task.services.tasks.tasks_filter_services import TasksFilterService


def make_mock_db():
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    db.begin = MagicMock(return_value=tx)
    return db


def make_task_dict(**kwargs):
    task = {
        "id": "task-1",
        "userId": "owner",
        "title": "Task",
        "notes": "",
        "priorityLevel": 1,
        "status": "Todo",
    }
    task.update(kwargs)
    return task


def run_task_mutation(query, task):
    """Runs a task mutation with the service mocked; returns (result, service)."""
    service = MagicMock()
    service.find_one = AsyncMock(return_value=task)
    service.create = AsyncMock(return_value=task)
    service.update = AsyncMock(return_value=task)

    async def find_owned(self, id, user_id):
        return MagicMock(id=id, userId=user_id)

    patches = [
        patch(
            "app.modules.task.graphql.tasks_mutations.TasksService",
            MagicMock(return_value=service),
        ),
        patch("app.modules.task.graphql.tasks_mutations.AuthService", MagicMock()),
        patch(
            "app.modules.google_calendar.services.google_calendar_service.GoogleCalendarService",
            MagicMock(),
        ),
        patch(
            "app.modules.task.services.scheduler_service.SchedulerService", MagicMock()
        ),
        patch(
            "app.modules.workspace.services.workspaces_service.WorkspacesService.find_one",
            find_owned,
        ),
        patch(
            "app.modules.workspace.services.project_groups_service.ProjectGroupsService.find_one",
            find_owned,
        ),
    ]

    async def run():
        for p in patches:
            p.start()
        try:
            return await schema.execute(
                query, context_value={"db": make_mock_db(), "user_id": "owner"}
            )
        finally:
            for p in patches:
                p.stop()

    return run, service


def sent_update(service) -> dict:
    return service.update.await_args.args[1]


@pytest.mark.anyio
async def test_create_task_without_deadline_reaches_the_service():
    run, service = run_task_mutation(
        """
        mutation {
          createTask(createTaskInput: {
            user_id: "ignored", title: "Sin fecha", notes: "", priority_level: 2,
            tags: [], project_id: "group-1"
          }) { id }
        }
        """,
        make_task_dict(),
    )
    result = await run()

    assert result.errors is None
    service.create.assert_awaited_once()
    assert service.create.await_args.args[0]["deadline"] is None


@pytest.mark.anyio
async def test_update_task_leaves_links_alone_when_omitted():
    run, service = run_task_mutation(
        'mutation { updateTask(updateTaskInput: { id: "task-1", title: "x" }) { id } }',
        make_task_dict(workspaceId="ws-1", projectId="group-1"),
    )
    result = await run()

    assert result.errors is None
    assert "workspaceId" not in sent_update(service)
    assert "projectId" not in sent_update(service)


@pytest.mark.anyio
async def test_update_task_null_unlinks_workspace_and_project():
    run, service = run_task_mutation(
        'mutation { updateTask(updateTaskInput: { id: "task-1", workspace_id: null, project_id: null }) { id } }',
        make_task_dict(workspaceId="ws-1", projectId="group-1"),
    )
    result = await run()

    assert result.errors is None
    assert sent_update(service)["workspaceId"] is None
    assert sent_update(service)["projectId"] is None


@pytest.mark.anyio
async def test_update_task_still_accepts_legacy_null_strings():
    run, service = run_task_mutation(
        'mutation { updateTask(updateTaskInput: { id: "task-1", workspace_id: "null", project_id: "" }) { id } }',
        make_task_dict(workspaceId="ws-1", projectId="group-1"),
    )
    result = await run()

    assert result.errors is None
    assert sent_update(service)["workspaceId"] is None
    assert sent_update(service)["projectId"] is None


def test_search_condition_covers_tags_and_the_users_project_names():
    sql = str(
        select(Task.id)
        .where(search_term_condition("sec", "user-1"))
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "json_array_elements" in sql
    # Rows whose tags aren't an array are read as empty instead of erroring.
    assert "json_typeof" in sql
    assert "->> 'name'" in sql
    # Project names are only matched among the caller's own projects.
    assert '"ProjectGroup"."userId" = \'user-1\'' in sql


def test_in_memory_search_matches_tag_names():
    tasks = [
        {"id": "a", "title": "Login", "notes": "", "tags": [{"name": "Security"}]},
        {"id": "b", "title": "Docs", "notes": "", "tags": [{"name": "Writing"}]},
        {"id": "c", "title": "Bad tags", "notes": "", "tags": None},
    ]

    result = TasksFilterService().apply_filters_and_sorting(
        tasks, {"searchTerm": "secur"}
    )

    assert [t["id"] for t in result] == ["a"]


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["null", '""'])
async def test_update_task_null_or_empty_removes_the_date(value):
    run, service = run_task_mutation(
        f'mutation {{ updateTask(updateTaskInput: {{ id: "task-1", deadline: {value} }}) {{ id }} }}',
        make_task_dict(),
    )
    result = await run()

    assert result.errors is None
    assert sent_update(service)["deadline"] is None


@pytest.mark.anyio
async def test_update_task_keeps_the_date_when_omitted():
    run, service = run_task_mutation(
        'mutation { updateTask(updateTaskInput: { id: "task-1", title: "x" }) { id } }',
        make_task_dict(),
    )
    result = await run()

    assert result.errors is None
    assert "deadline" not in sent_update(service)


@pytest.mark.anyio
async def test_update_task_rejects_a_malformed_date_instead_of_wiping_it():
    run, service = run_task_mutation(
        'mutation { updateTask(updateTaskInput: { id: "task-1", deadline: "next tuesday" }) { id } }',
        make_task_dict(),
    )
    result = await run()

    assert result.errors is not None
    service.update.assert_not_called()


@pytest.mark.anyio
async def test_update_task_parses_a_new_date():
    run, service = run_task_mutation(
        'mutation { updateTask(updateTaskInput: { id: "task-1", deadline: "2026-10-03T06:00:00.000Z" }) { id } }',
        make_task_dict(),
    )
    result = await run()

    assert result.errors is None
    assert sent_update(service)["deadline"].isoformat() == "2026-10-03T06:00:00"
