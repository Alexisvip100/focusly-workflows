"""Insights only shows what the user's data says: no made-up comparisons, and
no score before there's anything to score."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.insights.services import insights_service as module
from app.modules.insights.services.insights_service import InsightsService


def service():
    return InsightsService(MagicMock())


def test_no_score_while_nothing_is_finished():
    score = service().calculate_energy_score(
        [{"status": "Todo"}, {"status": "Backlog"}]
    )
    assert score == {"value": "N/A", "change": "", "trend": "neutral"}


def test_without_tracked_time_only_what_was_finished_counts():
    score = service().calculate_energy_score(
        [{"status": "Done"}, {"status": "Todo"}]
    )
    assert score["value"] == "50/100"
    assert score["change"] == ""


def test_with_tracked_time_efficiency_counts():
    score = service().calculate_energy_score(
        [{"status": "Done", "estimateTimer": 30, "realTimer": 30}]
    )
    assert score["value"] == "100/100"


@pytest.mark.anyio
async def test_no_comparison_with_a_previous_period_is_invented(monkeypatch):
    tasks_repo = MagicMock()
    tasks_repo.get_all_active_by_user = AsyncMock(return_value=[])
    tasks_repo.get_deleted_done_by_user = AsyncMock(return_value=[])
    sessions = SimpleNamespace(get_all_by_user=AsyncMock(return_value=[]))
    users = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    monkeypatch.setattr(module, "TasksRepository", lambda db: tasks_repo)
    monkeypatch.setattr(module, "FocusSessionsRepository", lambda db: sessions)
    monkeypatch.setattr(module, "UsersRepository", lambda db: users)

    insights = await service().getInsights("u1", "Weekly")

    for key in ("totalFocusHours", "taskCompletion", "energyScore"):
        assert insights[key]["change"] == ""
        assert insights[key]["trend"] == "neutral"
