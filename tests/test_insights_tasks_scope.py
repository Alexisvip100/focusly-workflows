"""Insights built without a TasksService (the AI context does this) read
only the asking user's tasks. It used to call get_active_non_google_tasks
with a user id it doesn't take, so Lumina's context lost its insights on
every message ("takes 1 positional argument but 2 were given") — and that
method returns every user's tasks, so it couldn't be the fix either."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Task
from app.modules.insights.services import insights_service as module
from app.modules.insights.services.insights_service import InsightsService


@pytest.mark.anyio
async def test_insights_without_a_tasks_service_read_only_this_users_tasks(
    monkeypatch,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    mine = Task(
        id="t1",
        userId="u1",
        title="Mía",
        status="Done",
        estimated_start_date=now - timedelta(hours=3),
        estimated_end_date=now - timedelta(hours=2),
        completedAt=now - timedelta(hours=2),
    )

    tasks_repo = MagicMock()
    tasks_repo.get_all_active_by_user = AsyncMock(return_value=[mine])
    tasks_repo.get_active_non_google_tasks = AsyncMock(
        side_effect=AssertionError("must not read every user's tasks")
    )
    sessions_repo = SimpleNamespace(get_all_by_user=AsyncMock(return_value=[]))
    users_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    monkeypatch.setattr(module, "TasksRepository", lambda db: tasks_repo)
    monkeypatch.setattr(module, "FocusSessionsRepository", lambda db: sessions_repo)
    monkeypatch.setattr(module, "UsersRepository", lambda db: users_repo)

    insights = await InsightsService(MagicMock()).getInsights("u1", "Weekly")

    tasks_repo.get_all_active_by_user.assert_awaited_once_with("u1")
    tasks_repo.get_active_non_google_tasks.assert_not_called()
    assert insights["taskCompletion"]["value"]


@pytest.mark.anyio
async def test_lumina_context_keeps_the_insights_block(monkeypatch):
    from app.modules.ai.services import context_builder

    monkeypatch.setattr(context_builder.cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(context_builder.cache, "set", AsyncMock(return_value=True))
    tasks_repo = MagicMock()
    tasks_repo.get_all_active_by_user = AsyncMock(return_value=[])
    monkeypatch.setattr(module, "TasksRepository", lambda db: tasks_repo)
    monkeypatch.setattr(
        module,
        "FocusSessionsRepository",
        lambda db: SimpleNamespace(get_all_by_user=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(
        module,
        "UsersRepository",
        lambda db: SimpleNamespace(get_by_id=AsyncMock(return_value=None)),
    )

    text = await context_builder.insights_block(MagicMock(), "u1")

    assert "USER PRODUCTIVITY INSIGHTS" in text
