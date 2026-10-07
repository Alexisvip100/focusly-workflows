"""What Lumina sends to the models: the model per message, a short history,
a cacheable context, the token count of each reply and the plan limits of the
planners."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.modules.ai.routes import ai as ai_routes
from app.modules.ai.routes import planner as planner_routes
from app.modules.ai.services import context_builder as cb
from app.modules.ai.services.chat_payload import (
    FULL_RECENT_MESSAGES,
    HISTORY_WINDOW,
    OLD_MESSAGE_CHARS,
    build_history,
    compact_attachments,
)
from app.modules.ai.services.context_builder import AIContext
from app.modules.ai.services.focusly_ai import (
    USAGE_MARKER,
    UsageTrailer,
    focusly_ai_headers,
    total_tokens,
)
from app.modules.ai.services.memory import EXTRACT_EVERY_N_MESSAGES, worth_extracting
from app.modules.ai.services.prompts import ONE_SHOT_PROMPT
from app.modules.ai.services.router import LIGHT_MODEL, STRONG_MODEL, pick_model
from app.modules.billing.plans import FREE_AI_MESSAGE_LIMIT
from app.routes.common import get_current_user_id

NOW = datetime(2026, 10, 6, 12, 0)
FILE = (
    "=== ATTACHED FILE: plan.pdf ===\n" + "contenido " * 500 + "\n=== END OF FILE ==="
)


# ─── Model ─────────────────────────────────────────────────────────────────────


class TestPickModel:
    @pytest.mark.parametrize(
        "query",
        [
            "hola",
            "gracias!",
            "crea una tarea para mañana a las 5",
            "marca X como hecha",
        ],
    )
    def test_quick_requests_use_the_light_model(self, query):
        assert pick_model(None, query) == LIGHT_MODEL

    @pytest.mark.parametrize(
        "query",
        [
            "Organiza mi semana",
            "planifica el lanzamiento del proyecto",
            "¿Por qué no avanzo con mis tareas?",
            "prioriza mis pendientes",
            "Analyze my week",
            "- uno\n- dos\n- tres",
            "x" * 600,
        ],
    )
    def test_planning_and_long_requests_use_the_strong_model(self, query):
        assert pick_model(None, query) == STRONG_MODEL

    def test_attachments_use_the_strong_model(self):
        assert pick_model(None, "revisa", has_attachments=True) == STRONG_MODEL

    def test_a_choice_we_offer_is_respected(self):
        assert pick_model(STRONG_MODEL, "hola") == STRONG_MODEL
        assert pick_model(LIGHT_MODEL, "organiza mi semana") == LIGHT_MODEL
        # Older app versions name versions.
        assert pick_model("gemini-2.5-flash", "hola") == STRONG_MODEL

    @pytest.mark.parametrize(
        "requested", ["auto", "claude-3-opus", "gemini-1.5-flash", None]
    )
    def test_retired_or_unknown_models_are_picked_here(self, requested):
        assert pick_model(requested, "hola") == LIGHT_MODEL


# ─── History ───────────────────────────────────────────────────────────────────


class TestHistory:
    def test_keeps_a_window_of_recent_messages(self):
        messages = [("user" if i % 2 == 0 else "assistant", f"m{i}") for i in range(40)]
        history = build_history(messages)
        assert len(history) <= HISTORY_WINDOW
        assert history[-1] == {"role": "assistant", "content": "m39"}
        assert history[0]["role"] == "user"

    def test_older_attachments_become_a_mention(self):
        messages = [("user", f"Revisa esto\n{FILE}"), ("assistant", "Listo")] + [
            ("user", "ok"),
            ("assistant", "ok"),
        ] * FULL_RECENT_MESSAGES
        history = build_history(messages)
        assert "contenido" not in history[0]["content"]
        assert "[Attached file: plan.pdf" in history[0]["content"]

    def test_the_current_message_keeps_its_file(self):
        history = build_history([("user", f"Revisa esto\n{FILE}")])
        assert "contenido contenido" in history[0]["content"]

    def test_older_replies_keep_which_actions_they_proposed(self):
        reply = (
            'Te propongo esto.\n[ACTION: CREATE_TASK {"title": "Escribir informe", '
            '"notes": "' + "n" * 2000 + '"}]'
        )
        messages = [("user", "plan"), ("assistant", reply)] + [
            ("user", "ok"),
            ("assistant", "ok"),
        ] * FULL_RECENT_MESSAGES
        old_reply = build_history(messages)[1]["content"]
        assert "CREATE_TASK «Escribir informe»" in old_reply
        assert len(old_reply) < OLD_MESSAGE_CHARS + 200

    def test_merges_turns_of_the_same_role_and_starts_with_the_user(self):
        history = build_history(
            [("assistant", "hola"), ("user", "a"), ("user", "b"), ("assistant", "c")]
        )
        assert history == [
            {"role": "user", "content": "a\n\nb"},
            {"role": "assistant", "content": "c"},
        ]

    def test_compact_attachments_without_end_marker(self):
        assert compact_attachments("=== ATTACHED FILE: a.txt ===\ntexto") == (
            "[Attached file: a.txt — already reviewed]"
        )


# ─── Context ───────────────────────────────────────────────────────────────────


def make_task(**kwargs):
    defaults = dict(
        id="t1",
        title="Escribir informe",
        status="Todo",
        priorityLevel=2,
        estimated_start_date=None,
        estimated_end_date=None,
        deadline=NOW + timedelta(days=20),
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


class TestTaskIndex:
    def test_one_line_with_what_scheduling_needs(self):
        line = cb.format_task_index(
            make_task(
                estimated_start_date=NOW,
                estimated_end_date=NOW + timedelta(hours=1),
                projectId="p1",
                subtasks=[{"title": "a", "completed": True}, {"title": "b"}],
                notes="notas largas que no van en el índice",
            )
        )
        assert line.count("\n") == 1
        assert "- ID: t1 | Escribir informe | Todo | P2" in line
        assert "2026-10-06T12:00 → 2026-10-06T13:00" in line
        assert "project p1" in line
        assert "1/2 subtasks" in line
        assert "notas" not in line

    def test_details_for_the_tasks_the_message_names_and_the_urgent_ones(self):
        tasks = [
            make_task(id="named", title="Preparar presentación cliente"),
            make_task(
                id="urgent", title="Pagar renta", deadline=NOW + timedelta(days=1)
            ),
            make_task(id="other", title="Leer libro"),
            make_task(id="done", title="Presentación vieja", status="Done"),
        ]
        detailed = cb.pick_detailed_tasks(tasks, "¿cómo voy con la presentación?", NOW)
        assert [t.id for t in detailed] == ["named", "urgent"]

    def test_caps_the_detailed_tasks(self):
        tasks = [
            make_task(id=f"t{i}", deadline=NOW + timedelta(hours=i))
            for i in range(cb.MAX_DETAILED_TASKS + 5)
        ]
        assert len(cb.pick_detailed_tasks(tasks, "", NOW)) == cb.MAX_DETAILED_TASKS


class TestCalendarEvents:
    def test_next_week_in_full_later_ones_in_one_line(self):
        now = datetime(2026, 10, 6, 12, 0).astimezone()
        soon = {
            "id": "soon",
            "summary": "Sync",
            "start": {"dateTime": (now + timedelta(days=1)).isoformat()},
            "end": {"dateTime": (now + timedelta(days=1, hours=1)).isoformat()},
        }
        later = {
            "id": "later",
            "summary": "Viaje",
            "start": {"date": (now + timedelta(days=20)).date().isoformat()},
            "end": {"date": (now + timedelta(days=21)).date().isoformat()},
        }
        synced = {**soon, "id": "synced"}
        text = cb.format_calendar_events([soon, later, synced], {"synced"}, now)
        assert "- ID: soon\n" in text
        assert "Google Meet:" in text
        assert "- ID: later | Viaje |" in text
        assert "synced" not in text

    @pytest.mark.anyio
    async def test_calendar_is_read_from_the_cache(self, monkeypatch):
        cache = SimpleNamespace(
            get=AsyncMock(return_value=[{"id": "ev"}]), set=AsyncMock()
        )
        monkeypatch.setattr(cb, "cache", cache)
        assert await cb.get_calendar_items(MagicMock(), "user-1") == [{"id": "ev"}]
        cache.set.assert_not_called()


class TestAIContext:
    def test_the_stable_part_goes_first(self):
        context = AIContext("instrucciones\n")
        context.add("hora: 10:00\n")
        assert context.text == "instrucciones\nhora: 10:00\n"
        assert context.text.startswith(context.stable)

    def test_one_shot_has_no_user_data(self):
        assert cb.one_shot_context().text == ONE_SHOT_PROMPT


# ─── focusly-ai ────────────────────────────────────────────────────────────────


class TestUsageTrailer:
    def test_splits_text_and_usage_across_chunks(self):
        trailer = UsageTrailer()
        out = trailer.feed("Hola ")
        out += trailer.feed("mundo" + USAGE_MARKER + '{"input": 10')
        out += trailer.feed(', "output": 5, "thoughts": 2}')
        assert out == "Hola mundo"
        assert trailer.usage == {"input": 10, "output": 5, "thoughts": 2}
        assert total_tokens(trailer.usage) == 17

    def test_no_trailer(self):
        trailer = UsageTrailer()
        assert trailer.feed("Hola") == "Hola"
        assert trailer.usage is None
        assert total_tokens(None) == 0

    def test_internal_token_header(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.ai.services.focusly_ai.settings.FOCUSLY_AI_INTERNAL_TOKEN",
            "s3cret",
        )
        assert focusly_ai_headers() == {"X-Internal-Token": "s3cret"}
        monkeypatch.setattr(
            "app.modules.ai.services.focusly_ai.settings.FOCUSLY_AI_INTERNAL_TOKEN", ""
        )
        assert focusly_ai_headers() == {}


class TestMemoryGate:
    @pytest.mark.parametrize(
        "message",
        [
            "Recuerda que prefiero trabajar de noche",
            "Mi jefe se llama Luis",
            "I prefer mornings",
        ],
    )
    def test_personal_messages_are_read(self, message):
        assert worth_extracting(message, 1)

    def test_other_messages_only_every_few(self):
        assert not worth_extracting("crea una tarea para mañana", 1)
        assert worth_extracting("crea una tarea para mañana", EXTRACT_EVERY_N_MESSAGES)

    def test_attached_files_dont_count(self):
        file = "=== ATTACHED FILE: cv.txt ===\nMe llamo Ana y prefiero...\n=== END OF FILE ==="
        assert not worth_extracting(f"revisa\n{file}", 1)


# ─── Chat route ────────────────────────────────────────────────────────────────


@pytest.fixture
def chat(monkeypatch):
    conv_repo = MagicMock()
    conv_repo.create = AsyncMock()
    conv_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id="conv-1", userId="user-1", workspaceId=None)
    )
    conv_repo.touch = AsyncMock()
    msg_repo = MagicMock()
    msg_repo.create = AsyncMock()
    msg_repo.get_by_conversation_id = AsyncMock(return_value=[])
    streamed = {}

    async def fake_stream(messages, system_context, model, *args, **kwargs):
        streamed.update(
            messages=messages, context=system_context, model=model, **kwargs
        )
        yield "hola"

    build = AsyncMock(return_value=AIContext("ctx"))
    monkeypatch.setattr(ai_routes, "ConversationRepository", lambda db: conv_repo)
    monkeypatch.setattr(ai_routes, "MessageRepository", lambda db: msg_repo)
    monkeypatch.setattr(ai_routes, "build_context", build)
    monkeypatch.setattr(ai_routes, "stream_gemini_and_save", fake_stream)

    app = FastAPI()
    app.include_router(ai_routes.router)
    db = MagicMock()
    db.commit = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(subscriptionStatus="pro"))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    return TestClient(app), SimpleNamespace(
        msg=msg_repo, streamed=streamed, build=build
    )


def stored(role, content):
    return SimpleNamespace(role=role, content=content)


class TestChatPayload:
    def test_history_comes_from_the_database(self, chat):
        client, state = chat
        state.msg.get_by_conversation_id.return_value = [
            stored("user", "hola"),
            stored("assistant", "¡Hola!"),
            stored("user", "crea una tarea"),
        ]
        client.post(
            "/ai/chat",
            json={
                "messages": [{"role": "user", "content": "crea una tarea"}],
                "conversationId": "conv-1",
            },
        )
        assert state.streamed["messages"] == [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "¡Hola!"},
            {"role": "user", "content": "crea una tarea"},
        ]
        assert state.streamed["model"] == LIGHT_MODEL

    def test_a_history_sent_by_the_client_is_used(self, chat):
        # A retry drops the replies after the retried message.
        client, state = chat
        state.msg.get_by_conversation_id.return_value = [stored("user", "viejo")]
        client.post(
            "/ai/chat",
            json={
                "messages": [
                    {"role": "user", "content": "hola"},
                    {"role": "assistant", "content": "¡Hola!"},
                    {"role": "user", "content": "otra vez"},
                ],
                "conversationId": "conv-1",
            },
        )
        assert [m["content"] for m in state.streamed["messages"]] == [
            "hola",
            "¡Hola!",
            "otra vez",
        ]

    def test_one_shot_rewrites_get_no_user_data(self, chat):
        client, state = chat
        client.post(
            "/ai/chat",
            json={
                "messages": [{"role": "user", "content": "Acorta esto"}],
                "persist": False,
            },
        )
        state.build.assert_not_called()
        assert state.streamed["context"].text == ONE_SHOT_PROMPT
        assert state.streamed["extract_memory"] is False

    def test_the_editor_gets_the_light_context(self, chat):
        client, state = chat
        client.post(
            "/ai/chat",
            json={
                "messages": [{"role": "user", "content": "Resume"}],
                "document_context": "# Doc",
                "persist": False,
            },
        )
        assert state.build.call_args.kwargs["mode"] == "editor"
        assert state.streamed["context"].text.endswith("# Doc")
        assert state.streamed["extract_memory"] is False

    def test_the_chat_gets_the_full_context(self, chat):
        client, state = chat
        client.post(
            "/ai/chat",
            json={
                "messages": [{"role": "user", "content": "Recuerda que soy diseñadora"}]
            },
        )
        assert state.build.call_args.kwargs["mode"] == "full"
        assert state.streamed["extract_memory"] is True


# ─── Planner limits ────────────────────────────────────────────────────────────


@pytest.fixture
def planner(monkeypatch):
    state = SimpleNamespace(
        user=SimpleNamespace(subscriptionStatus="free"),
        consume=AsyncMock(return_value=2),
        refund=AsyncMock(),
        status=200,
        calls=[],
    )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json, headers, timeout):
            state.calls.append({"url": url, "headers": headers})
            return SimpleNamespace(status_code=state.status, json=lambda: {"plan": []})

    monkeypatch.setattr(planner_routes.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(planner_routes, "consume_ai_message", state.consume)
    monkeypatch.setattr(planner_routes, "refund_ai_message", state.refund)
    monkeypatch.setattr(
        "app.modules.ai.services.focusly_ai.settings.FOCUSLY_AI_INTERNAL_TOKEN", "tok"
    )

    app = FastAPI()
    app.include_router(planner_routes.router)
    db = MagicMock()
    db.get = AsyncMock(side_effect=lambda model, id: state.user)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    return TestClient(app), state


class TestPlannerLimits:
    def test_free_users_spend_a_message(self, planner):
        client, state = planner
        response = client.post("/ai/planner/organize", json={"tasks": []})
        assert response.status_code == 200
        state.consume.assert_awaited_once()
        assert response.headers["X-AI-Messages-Remaining"] == str(
            FREE_AI_MESSAGE_LIMIT - 2
        )
        assert state.calls[0]["headers"] == {"X-Internal-Token": "tok"}

    def test_over_the_limit_asks_for_pro(self, planner):
        client, state = planner
        state.consume.return_value = None
        response = client.post(
            "/ai/planner/improve", json={"title": "x", "mode": "all"}
        )
        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "free_limit_reached"
        assert state.calls == []

    def test_a_failed_call_gives_the_message_back(self, planner):
        client, state = planner
        state.status = 500
        response = client.post("/ai/planner/weekly", json={"tasks": []})
        assert response.status_code == 502
        state.refund.assert_awaited_once()

    def test_pro_users_are_not_counted(self, planner):
        client, state = planner
        state.user.subscriptionStatus = "pro"
        response = client.post(
            "/ai/planner/calendar", json={"tasks": [], "free_slots": []}
        )
        assert response.status_code == 200
        state.consume.assert_not_called()
        assert "X-AI-Messages-Remaining" not in response.headers


class TestGeminiRest:
    @pytest.mark.parametrize(
        "model, config",
        [
            ("gemini-2.5-flash-lite", {"thinkingBudget": 0}),
            ("gemini-3.5-flash-lite", {"thinkingLevel": "minimal"}),
        ],
    )
    def test_no_thinking_per_model_family(self, model, config):
        from app.modules.ai.services.gemini_rest import no_thinking

        assert no_thinking(model) == config
