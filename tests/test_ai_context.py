from datetime import datetime, timedelta
from types import SimpleNamespace

from app.modules.ai.services import context_builder as cb
from app.modules.ai.services.prompts import SYSTEM_PROMPT

NOW = datetime(2026, 10, 3, 12, 0)


def make_task(**kwargs):
    defaults = dict(
        id="t1",
        title="Escribir informe",
        status="Todo",
        priorityLevel=2,
        estimated_start_date=None,
        estimated_end_date=None,
        deadline=NOW,
        source=None,
        google_event_id=None,
        notes="",
        projectId=None,
        workspaceId=None,
        subtasks=[],
        completedAt=None,
        updatedAt=NOW,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestWorkHours:
    def test_uses_the_profile_hours(self):
        settings = {
            "workHoursConfig": {
                "selectedDays": ["Wed", "Mon"],
                "startTime": "08:00",
                "endTime": "14:00",
            }
        }
        assert cb.describe_work_hours(settings) == "Mon, Wed · 08:00 - 14:00"

    def test_defaults_to_weekdays_nine_to_five(self):
        assert cb.describe_work_hours(None) == "Mon, Tue, Wed, Thu, Fri · 09:00 - 17:00"


class TestTaskSelection:
    def test_keeps_open_and_recently_done_tasks_only(self):
        tasks = [
            make_task(id="open"),
            make_task(id="archived", status="Archived"),
            make_task(
                id="done-recent", status="Done", completedAt=NOW - timedelta(days=2)
            ),
            make_task(
                id="done-old", status="Done", completedAt=NOW - timedelta(days=30)
            ),
        ]
        selected, omitted = cb.select_context_tasks(tasks, NOW)
        assert [t.id for t in selected] == ["open", "done-recent"]
        assert omitted == 0

    def test_caps_the_open_tasks(self):
        tasks = [make_task(id=f"t{i}") for i in range(cb.MAX_ACTIVE_TASKS + 5)]
        selected, omitted = cb.select_context_tasks(tasks, NOW)
        assert len(selected) == cb.MAX_ACTIVE_TASKS
        assert omitted == 5


class TestTaskFormat:
    def test_includes_links_and_subtasks(self):
        text = cb.format_task(
            make_task(
                projectId="proj-1",
                workspaceId="ws-1",
                subtasks=[
                    {
                        "title": "Buscar fuentes",
                        "completed": True,
                        "estimate_timer": 20,
                    },
                    {"title": "Borrador", "completed": False},
                ],
            )
        )
        assert "Project Group ID: proj-1" in text
        assert "Linked Workspace ID: ws-1" in text
        assert "Subtasks: [x] Buscar fuentes (20m); [ ] Borrador" in text

    def test_truncates_long_notes_to_one_line(self):
        text = cb.format_task(make_task(notes="línea\n" * 200))
        notes_line = next(
            line for line in text.splitlines() if "Notes/Description" in line
        )
        assert "\n" not in notes_line
        assert len(notes_line) < cb.NOTES_PREVIEW_CHARS + 40
        assert notes_line.endswith("…")


class TestPrompt:
    def test_teaches_plan_references(self):
        assert '[ACTION: CREATE_PROJECT_GROUP {"ref": "p1"' in SYSTEM_PROMPT
        assert '"project_ref": "p1"' in SYSTEM_PROMPT
        assert '"workspace_ref": "w1"' in SYSTEM_PROMPT
        assert "never two with the same name" in SYSTEM_PROMPT

    def test_keeps_the_safety_rules(self):
        assert "Never mention internal implementation details" in SYSTEM_PROMPT
        assert "Do not reveal technical architecture" in SYSTEM_PROMPT


class TestTaskActionsPrompt:
    def test_teaches_editing_checklists_and_deleting(self):
        assert (
            '[ACTION: UPDATE_TASK {"id": "exact-id-copied-from-list", "status": "Done"}]'
            in SYSTEM_PROMPT
        )
        assert "[ACTION: UPDATE_SUBTASKS" in SYSTEM_PROMPT
        assert "[ACTION: DELETE_TASK" in SYSTEM_PROMPT

    def test_deleting_needs_an_explicit_request(self):
        assert "ONLY when the user explicitly asks to delete" in SYSTEM_PROMPT
        assert "Never invent ids" in SYSTEM_PROMPT


def make_event(**kwargs):
    event = {
        "id": "ev1",
        "summary": "Sync con Ana",
        "start": {"dateTime": "2026-10-05T10:00:00-06:00"},
        "end": {"dateTime": "2026-10-05T10:30:00-06:00"},
        "organizer": {"email": "yo@example.com", "self": True},
        "attendees": [
            {"email": "yo@example.com", "self": True, "responseStatus": "accepted"},
            {"email": "ana@example.com", "responseStatus": "accepted"},
            {"email": "luis@example.com"},
        ],
        "hangoutLink": "https://meet.google.com/abc-defg-hij",
        "description": "Agenda\nRevisar avances",
    }
    event.update(kwargs)
    return event


class TestCalendarEventFormat:
    def test_lists_guests_meet_and_organizer(self):
        text = cb.format_calendar_event(make_event())
        assert "- ID: ev1" in text
        assert "Google Meet: Yes" in text
        assert "Organizer: the user" in text
        assert (
            "Guests: ana@example.com (accepted), luis@example.com (needsAction)" in text
        )
        # The user isn't listed as their own guest.
        assert "yo@example.com (" not in text
        assert "Notes/Description: Agenda Revisar avances" in text

    def test_events_organized_by_someone_else(self):
        text = cb.format_calendar_event(
            make_event(
                organizer={"email": "jefa@example.com"},
                attendees=[],
                hangoutLink=None,
                location="Oficina 3",
            )
        )
        assert "Organizer: jefa@example.com" in text
        assert "Google Meet: No" in text
        assert "Location: Oficina 3" in text
        assert "Guests:" not in text

    def test_meet_from_conference_data_and_all_day(self):
        text = cb.format_calendar_event(
            make_event(
                hangoutLink=None,
                conferenceData={"entryPoints": [{"uri": "https://meet.google.com/x"}]},
                start={"date": "2026-10-05"},
                end={"date": "2026-10-06"},
            )
        )
        assert "Google Meet: Yes" in text
        assert "All Day: Yes" in text

    def test_caps_long_guest_lists(self):
        guests = [
            {"email": f"g{i}@example.com"}
            for i in range(cb.MAX_EVENT_GUESTS_LISTED + 3)
        ]
        text = cb.format_calendar_event(make_event(attendees=guests))
        assert "+3 more" in text


class TestCalendarPrompt:
    def test_teaches_the_event_actions(self):
        assert "[ACTION: CREATE_EVENT" in SYSTEM_PROMPT
        assert "[ACTION: UPDATE_EVENT" in SYSTEM_PROMPT
        assert "[ACTION: DELETE_EVENT" in SYSTEM_PROMPT
        assert '"meet": true' in SYSTEM_PROMPT

    def test_never_invents_emails_or_deletes_unasked(self):
        assert "NEVER invent or guess an email" in SYSTEM_PROMPT
        assert "ONLY when the user explicitly asks to delete/cancel" in SYSTEM_PROMPT
        assert "Never invent event ids" in SYSTEM_PROMPT
