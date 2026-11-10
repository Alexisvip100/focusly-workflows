"""Lumina reads and writes the user's local time. Tasks are stored in UTC, so
it used to tell someone in Mexico that a 05:05 task was at 11:05."""

from datetime import datetime
from types import SimpleNamespace

from app.modules.ai.services import context_builder as cb
from app.modules.ai.services.prompts import SYSTEM_PROMPT

MEXICO = cb.user_zone("America/Mexico_City")


def task(**kwargs):
    defaults = dict(
        id="t1",
        title="Reunión",
        status="Todo",
        priorityLevel=2,
        estimated_start_date=datetime(2026, 11, 11, 11, 5),
        estimated_end_date=datetime(2026, 11, 11, 11, 35),
        deadline=datetime(2026, 11, 12, 4, 37),
        source=None,
        google_event_id=None,
        notes="",
        projectId=None,
        workspaceId=None,
        subtasks=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_index_shows_local_times():
    line = cb.format_task_index(task(), MEXICO)
    assert "2026-11-11T05:05 → 2026-11-11T05:35" in line
    # 04:37 UTC is still the night before there
    assert "due 2026-11-11T22:37" in line


def test_details_show_local_times():
    text = cb.format_task(task(), MEXICO)
    assert "Start: 2026-11-11T05:05:00" in text
    assert "Deadline: 2026-11-11T22:37:00" in text


def test_without_a_zone_times_stay_as_stored():
    assert "2026-11-11T11:05 →" in cb.format_task_index(task())
    assert cb.user_zone(None) is None
    assert cb.user_zone("Marte/Olympus") is None


def test_prompt_treats_actions_as_proposals():
    assert "ACTIONS ARE PROPOSALS" in SYSTEM_PROMPT
    assert "Lo organicé dentro" not in SYSTEM_PROMPT
    assert "Creé el proyecto" not in SYSTEM_PROMPT


def test_prompt_asks_for_the_start_of_a_new_task():
    create_task = SYSTEM_PROMPT.split("Rules for CREATE_TASK")[0]
    assert '"estimated_start_date"' in create_task


def test_upcoming_dates_name_each_weekday():
    from datetime import date

    text = cb.upcoming_dates(date(2026, 11, 10))
    assert text.startswith("Wednesday 2026-11-11")
    assert "Friday 2026-11-13" in text
    assert text.endswith("Tuesday 2026-11-17")
