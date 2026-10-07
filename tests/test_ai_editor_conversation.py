from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.modules.ai.routes import ai as ai_routes
from app.modules.ai.services.context_builder import AIContext
from app.modules.ai.services.editor_blocks import (
    editor_message_preview,
    EDIT_END,
    EDIT_PLACEHOLDER,
    EDIT_START,
    REPLACEMENT_END,
    REPLACEMENT_START,
    strip_editor_blocks,
)
from app.routes.common import get_current_user_id


class TestStripEditorBlocks:
    def test_drops_a_whole_document_edit(self):
        reply = (
            f"Reordené las secciones.\n{EDIT_START}\n# Doc\nTodo el texto\n{EDIT_END}"
        )
        assert strip_editor_blocks(reply) == "Reordené las secciones."

    def test_drops_a_fragment_replacement(self):
        reply = (
            f"Lo hice más claro.\n{REPLACEMENT_START}\nTexto nuevo\n{REPLACEMENT_END}"
        )
        assert strip_editor_blocks(reply) == "Lo hice más claro."

    def test_unterminated_block_runs_to_the_end(self):
        reply = f"Cambios:\n{EDIT_START}\n# Doc cortado"
        assert strip_editor_blocks(reply) == "Cambios:"

    def test_block_only_reply_keeps_a_placeholder(self):
        assert strip_editor_blocks(f"{EDIT_START}\nx\n{EDIT_END}") == EDIT_PLACEHOLDER

    def test_plain_reply_is_untouched(self):
        assert strip_editor_blocks("  Hola  ") == "Hola"


@pytest.fixture
def chat_app(monkeypatch):
    conv_repo = MagicMock()
    conv_repo.create = AsyncMock()
    conv_repo.get_by_id = AsyncMock()
    conv_repo.get_latest_for_workspace = AsyncMock()
    conv_repo.list_for_workspace = AsyncMock(return_value=[])
    conv_repo.touch = AsyncMock()
    msg_repo = MagicMock()
    msg_repo.create = AsyncMock()
    msg_repo.get_by_conversation_id = AsyncMock(return_value=[])
    msg_repo.first_user_messages = AsyncMock(return_value={})
    ws_repo = MagicMock()
    ws_repo.get_by_id_and_user = AsyncMock()
    streamed = {}

    async def fake_stream(
        messages,
        system_context,
        model,
        background_tasks,
        user_id,
        conversation_id,
        user_message,
        db_factory,
        **kwargs,
    ):
        streamed["conversation_id"] = conversation_id
        streamed["messages"] = messages
        streamed["context"] = system_context
        streamed["model"] = model
        streamed.update(kwargs)
        yield "hola"

    monkeypatch.setattr(ai_routes, "ConversationRepository", lambda db: conv_repo)
    monkeypatch.setattr(ai_routes, "MessageRepository", lambda db: msg_repo)
    monkeypatch.setattr(ai_routes, "WorkspacesRepository", lambda db: ws_repo)
    monkeypatch.setattr(
        ai_routes, "build_context", AsyncMock(return_value=AIContext("ctx"))
    )
    monkeypatch.setattr(ai_routes, "stream_gemini_and_save", fake_stream)

    app = FastAPI()
    app.include_router(ai_routes.router)
    db = MagicMock()
    db.commit = AsyncMock()
    # The editor assistant is a Pro feature (see test_billing.py for limits).
    db.get = AsyncMock(return_value=SimpleNamespace(subscriptionStatus="pro"))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    return (
        TestClient(app),
        SimpleNamespace(conv=conv_repo, msg=msg_repo, ws=ws_repo, streamed=streamed),
    )


MESSAGES = [{"role": "user", "content": "Resume el documento"}]


class TestChatPersistence:
    def test_one_shot_call_saves_nothing(self, chat_app):
        client, repos = chat_app
        res = client.post("/ai/chat", json={"messages": MESSAGES, "persist": False})

        assert res.status_code == 200
        assert res.text == "hola"
        assert "x-conversation-id" not in res.headers
        repos.conv.create.assert_not_called()
        repos.msg.create.assert_not_called()
        assert repos.streamed["conversation_id"] is None

    def test_editor_thread_is_linked_to_the_document(self, chat_app):
        client, repos = chat_app
        repos.ws.get_by_id_and_user.return_value = SimpleNamespace(id="ws-1")

        res = client.post(
            "/ai/chat",
            json={
                "messages": MESSAGES,
                "workspaceId": "ws-1",
                "conversationTitle": "📝 Plan de lanzamiento",
            },
        )

        assert res.status_code == 200
        created = repos.conv.create.call_args.args[0]
        assert created.workspaceId == "ws-1"
        assert created.title == "📝 Plan de lanzamiento"
        assert res.headers["x-conversation-id"] == created.id
        repos.msg.create.assert_called_once()
        repos.ws.get_by_id_and_user.assert_awaited_with("ws-1", "user-1")

    def test_someone_elses_document_is_rejected(self, chat_app):
        client, repos = chat_app
        repos.ws.get_by_id_and_user.return_value = None

        res = client.post(
            "/ai/chat", json={"messages": MESSAGES, "workspaceId": "ws-x"}
        )

        assert res.status_code == 404
        repos.conv.create.assert_not_called()

    def test_continuing_a_thread_reuses_it(self, chat_app):
        client, repos = chat_app
        repos.conv.get_by_id.return_value = SimpleNamespace(
            id="conv-1", userId="user-1"
        )

        res = client.post(
            "/ai/chat", json={"messages": MESSAGES, "conversationId": "conv-1"}
        )

        assert res.status_code == 200
        assert res.headers["x-conversation-id"] == "conv-1"
        repos.conv.create.assert_not_called()
        # Continuing a thread moves it to the top of the history.
        repos.conv.touch.assert_awaited_once()


class TestWorkspaceConversation:
    def test_no_thread_yet(self, chat_app):
        client, repos = chat_app
        repos.conv.get_latest_for_workspace.return_value = None

        res = client.get("/ai/workspaces/ws-1/conversation")

        assert res.json() == {"conversationId": None, "messages": []}
        repos.conv.get_latest_for_workspace.assert_awaited_with("user-1", "ws-1")

    def test_returns_the_thread_without_editor_blocks(self, chat_app):
        client, repos = chat_app
        repos.conv.get_latest_for_workspace.return_value = SimpleNamespace(id="conv-1")
        repos.msg.get_by_conversation_id.return_value = [
            SimpleNamespace(
                id="m1",
                role="assistant",
                content=f"Listo.\n{EDIT_START}\n# Doc\n{EDIT_END}",
                createdAt=datetime(2026, 10, 2, 12, 0),
            )
        ]

        body = client.get("/ai/workspaces/ws-1/conversation").json()

        assert body["conversationId"] == "conv-1"
        assert body["messages"][0]["content"] == "Listo."


class TestWorkspaceConversationList:
    def test_lists_threads_with_a_preview_of_their_first_question(self, chat_app):
        client, repos = chat_app
        stamp = datetime(2026, 10, 2, 12, 0)
        repos.conv.list_for_workspace.return_value = [
            SimpleNamespace(id="c2", title="📝 Plan", createdAt=stamp, updatedAt=stamp),
            SimpleNamespace(id="c1", title="📝 Plan", createdAt=stamp, updatedAt=stamp),
        ]
        repos.msg.first_user_messages.return_value = {
            "c2": SimpleNamespace(
                content="Mejora esto.\n\n```selection\nun texto\n```"
            ),
        }

        body = client.get("/ai/workspaces/ws-1/conversations").json()

        repos.conv.list_for_workspace.assert_awaited_with("user-1", "ws-1")
        assert [c["id"] for c in body] == ["c2", "c1"]
        assert body[0]["preview"] == "Mejora esto."
        assert body[1]["preview"] == ""


class TestEditorMessagePreview:
    def test_drops_the_quoted_fragment(self):
        message = "Traduce esto.\n\n````selection\nusa ```js```\n````"
        assert editor_message_preview(message) == "Traduce esto."

    def test_collapses_whitespace_and_truncates(self):
        assert editor_message_preview("a  b\n c") == "a b c"
        long = "x" * 200
        preview = editor_message_preview(long, limit=10)
        assert len(preview) == 10 and preview.endswith("…")
