"""Regression tests: GraphQL resolvers must never expose or link another
user's tasks, workspaces or project groups, whatever IDs the client sends."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.graphql import schema
from app.graphql.dataloaders import get_loaders
from app.modules.task.graphql.tasks_mutations import ensure_owned_task_links


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
        "title": "Secret task",
        "notes": "secret notes",
        "priorityLevel": 1,
        "status": "TODO",
    }
    task.update(kwargs)
    return task


def mock_tasks_service(task):
    service = MagicMock()
    service.find_one = AsyncMock(return_value=task)
    service.create = AsyncMock(return_value=task)
    service.update = AsyncMock(return_value=task)
    return MagicMock(return_value=service), service


@pytest.mark.anyio
async def test_get_task_hides_other_users_task():
    tasks_cls, _ = mock_tasks_service(make_task_dict(userId="victim"))
    with patch("app.modules.task.graphql.tasks_queries.TasksService", tasks_cls):
        result = await schema.execute(
            '{ getTask(id: "task-1") { id title notes } }',
            context_value={"db": MagicMock(), "user_id": "attacker"},
        )

    assert result.data is None
    assert "Task with ID task-1 not found" in str(result.errors[0])


@pytest.mark.anyio
async def test_get_task_returns_own_task():
    tasks_cls, _ = mock_tasks_service(make_task_dict(userId="owner"))
    with patch("app.modules.task.graphql.tasks_queries.TasksService", tasks_cls):
        result = await schema.execute(
            '{ getTask(id: "task-1") { id title } }',
            context_value={"db": MagicMock(), "user_id": "owner"},
        )

    assert result.errors is None
    assert result.data == {"getTask": {"id": "task-1", "title": "Secret task"}}


@pytest.mark.anyio
async def test_get_tags_by_user_ignores_client_user_id():
    repo = MagicMock()
    repo.get_all_non_deleted_by_user = AsyncMock(return_value=[])
    with patch(
        "app.modules.task.repository.TasksRepository", MagicMock(return_value=repo)
    ):
        result = await schema.execute(
            '{ getTagsByUser(userId: "victim") { name } }',
            context_value={"db": MagicMock(), "user_id": "attacker"},
        )

    assert result.errors is None
    repo.get_all_non_deleted_by_user.assert_awaited_once_with("attacker")


@pytest.mark.anyio
async def test_get_insights_ignores_client_user_id():
    insights = MagicMock()
    # Stop right after the service call; only the user it was asked about matters.
    insights.getInsights = AsyncMock(side_effect=RuntimeError("stop"))
    with patch(
        "app.modules.insights.graphql.queries.InsightsService",
        MagicMock(return_value=insights),
    ):
        await schema.execute(
            '{ getInsights(userId: "victim") { totalFocusHours { value } } }',
            context_value={"db": MagicMock(), "user_id": "attacker"},
        )

    insights.getInsights.assert_awaited_once()
    assert insights.getInsights.call_args.args[0] == "attacker"


def make_loader_db():
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.anyio
async def test_workspace_loader_is_scoped_to_caller():
    import asyncio

    db = make_loader_db()
    loaders = get_loaders(db, asyncio.Lock(), "attacker")
    assert await loaders["task_workspace_loader"].load(("task-1", "victim-ws")) is None

    stmt = db.execute.call_args.args[0]
    assert "attacker" in stmt.compile().params.values()


@pytest.mark.anyio
async def test_project_loader_is_scoped_to_caller():
    import asyncio

    db = make_loader_db()
    loaders = get_loaders(db, asyncio.Lock(), "attacker")
    assert await loaders["project_by_id_loader"].load("victim-group") is None

    stmt = db.execute.call_args.args[0]
    assert "attacker" in stmt.compile().params.values()


@pytest.mark.anyio
async def test_loaders_resolve_nothing_without_a_user():
    import asyncio

    db = make_loader_db()
    loaders = get_loaders(db, asyncio.Lock(), None)
    assert await loaders["task_workspace_loader"].load(("task-1", "ws-1")) is None
    assert await loaders["project_by_id_loader"].load("group-1") is None
    db.execute.assert_not_called()


def patch_workspace_lookups(owner="owner"):
    """Workspaces / groups exist only for `owner`, mirroring find_one(id, user_id)."""

    async def find_one(self, id, user_id):
        if user_id != owner:
            raise ValueError(f"Not found: {id}")
        return MagicMock(id=id, userId=owner)

    return (
        patch(
            "app.modules.workspace.services.workspaces_service.WorkspacesService.find_one",
            find_one,
        ),
        patch(
            "app.modules.workspace.services.project_groups_service.ProjectGroupsService.find_one",
            find_one,
        ),
    )


@pytest.mark.anyio
async def test_ensure_owned_task_links():
    ws_patch, pg_patch = patch_workspace_lookups(owner="owner")
    with ws_patch, pg_patch:
        await ensure_owned_task_links(MagicMock(), "owner", "ws-1", "group-1")
        await ensure_owned_task_links(MagicMock(), "attacker", None, None)
        with pytest.raises(ValueError):
            await ensure_owned_task_links(MagicMock(), "attacker", "ws-1", None)
        with pytest.raises(ValueError):
            await ensure_owned_task_links(MagicMock(), "attacker", None, "group-1")


def patch_task_mutation_deps(tasks_cls):
    return (
        patch("app.modules.task.graphql.tasks_mutations.TasksService", tasks_cls),
        patch("app.modules.task.graphql.tasks_mutations.AuthService", MagicMock()),
        patch(
            "app.modules.google_calendar.services.google_calendar_service.GoogleCalendarService",
            MagicMock(),
        ),
        patch(
            "app.modules.task.services.scheduler_service.SchedulerService", MagicMock()
        ),
    )


CREATE_TASK = """
mutation {
  createTask(createTaskInput: {
    user_id: "ignored", title: "t", notes: "", priority_level: 1,
    deadline: "2026-10-01T00:00:00Z", tags: [], workspace_id: "victim-ws"
  }) { id }
}
"""


@pytest.mark.anyio
async def test_create_task_rejects_foreign_workspace():
    tasks_cls, service = mock_tasks_service(make_task_dict(userId="attacker"))
    ws_patch, pg_patch = patch_workspace_lookups(owner="victim")
    deps = patch_task_mutation_deps(tasks_cls)
    with ws_patch, pg_patch, deps[0], deps[1], deps[2], deps[3]:
        result = await schema.execute(
            CREATE_TASK, context_value={"db": make_mock_db(), "user_id": "attacker"}
        )

    assert result.errors is not None
    service.create.assert_not_called()


UPDATE_TASK_PROJECT = """
mutation {
  updateTask(updateTaskInput: { id: "task-1", project_id: "victim-group" }) { id }
}
"""


@pytest.mark.anyio
async def test_update_task_rejects_foreign_project():
    tasks_cls, service = mock_tasks_service(make_task_dict(userId="attacker"))
    ws_patch, pg_patch = patch_workspace_lookups(owner="victim")
    deps = patch_task_mutation_deps(tasks_cls)
    with ws_patch, pg_patch, deps[0], deps[1], deps[2], deps[3]:
        result = await schema.execute(
            UPDATE_TASK_PROJECT,
            context_value={"db": make_mock_db(), "user_id": "attacker"},
        )

    assert result.errors is not None
    service.update.assert_not_called()


@pytest.mark.anyio
async def test_update_task_allows_resending_current_link():
    task = make_task_dict(userId="owner", projectId="deleted-group")
    tasks_cls, service = mock_tasks_service(task)
    ws_patch, pg_patch = patch_workspace_lookups(owner="nobody")
    deps = patch_task_mutation_deps(tasks_cls)
    with ws_patch, pg_patch, deps[0], deps[1], deps[2], deps[3]:
        result = await schema.execute(
            'mutation { updateTask(updateTaskInput: { id: "task-1", project_id: "deleted-group" }) { id } }',
            context_value={"db": make_mock_db(), "user_id": "owner"},
        )

    assert result.errors is None
    service.update.assert_awaited_once()
