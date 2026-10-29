"""Lumina reads the text on a document's canvases along with the document."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Canvas, Workspace
from app.modules.ai.routes import ai as ai_routes
from app.modules.canvas.services import canvas_text
from app.modules.canvas.services.canvas_text import document_canvases_text, scene_text
from tests.test_ai_editor_conversation import MESSAGES, chat_app  # noqa: F401 (fixture)


def text(t, x, y, **extra):
    return {"type": "text", "text": t, "x": x, "y": y, **extra}


# ── The text of a drawing ────────────────────────────────────────────────────


def test_reads_the_text_top_to_bottom_and_left_to_right():
    scene = {
        "elements": [
            text("Then this", 300, 200),
            text("Title", 100, 10),
            text("Left", 100, 205),
            {"type": "rectangle", "x": 0, "y": 0},
        ]
    }
    assert scene_text(scene) == ["Title", "Left", "Then this"]


def test_takes_labels_frames_and_the_unwrapped_text():
    scene = {
        "elements": [
            # A label inside a shape: Excalidraw wraps it, originalText doesn't
            text("Launch\nplan", 0, 0, originalText="Launch plan", containerId="box"),
            {"type": "frame", "name": "Week 1", "x": 0, "y": 100},
            text("  spaced   out  ", 0, 200),
        ]
    }
    assert scene_text(scene) == ["Launch plan", "Week 1", "spaced out"]


def test_leaves_out_deleted_empty_and_repeated_text():
    scene = {
        "elements": [
            text("Gone", 0, 0, isDeleted=True),
            text("   ", 0, 50),
            text("Twice", 0, 100),
            text("Twice", 400, 300),
        ]
    }
    assert scene_text(scene) == ["Twice"]


@pytest.mark.parametrize("data", [None, {}, {"elements": "nope"}, [], {"elements": [None, 3]}])
def test_odd_scenes_have_no_text(data):
    assert scene_text(data) == []


# ── A document's canvases ────────────────────────────────────────────────────


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all(
            [
                Workspace(id="doc", userId="me", title="Doc", content=""),
                Canvas(
                    id="cv-plan", userId="me", workspaceId="doc", name="Plan", icon="🧭",
                    data={"elements": [text("Ship the beta", 0, 0)]},
                ),
                Canvas(
                    id="cv-blank", userId="me", workspaceId="doc", name="Blank",
                    data={"elements": [{"type": "ellipse", "x": 0, "y": 0}]},
                ),
                # Someone else's canvas pointing at the same document id
                Canvas(
                    id="cv-theirs", userId="them", workspaceId="doc", name="Secret",
                    data={"elements": [text("Their private note", 0, 0)]},
                ),
            ]
        )
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.anyio
async def test_gives_the_text_of_each_canvas_with_its_link(session):
    block = await document_canvases_text(session, "doc", "me")
    assert "--- CANVASES IN THIS DOCUMENT ---" in block
    assert 'Canvas "🧭 Plan" (linked in the document as [🧭 Plan](#canvas-cv-plan)):' in block
    assert "- Ship the beta" in block
    # A drawing without words adds nothing
    assert "Blank" not in block


@pytest.mark.anyio
async def test_only_reads_the_users_own_canvases(session):
    assert "Their private note" not in await document_canvases_text(session, "doc", "me")
    assert await document_canvases_text(session, "doc", "nobody") == ""


@pytest.mark.anyio
async def test_long_canvases_are_cut_to_fit(session, monkeypatch):
    monkeypatch.setattr(canvas_text, "MAX_CHARS_PER_CANVAS", 40)
    canvas = await session.get(Canvas, "cv-plan")
    canvas.data = {"elements": [text(f"Line {i} " + "x" * 20, 0, i * 30) for i in range(20)]}
    await session.commit()

    block = await document_canvases_text(session, "doc", "me")
    body = block.split("(#canvas-cv-plan)):\n")[1]
    assert len(body.strip()) <= 40
    assert body.strip().endswith("…")


# ── In Lumina's chat ─────────────────────────────────────────────────────────


@pytest.fixture
def canvases(monkeypatch):
    calls = []

    async def fake(db, workspace_id, user_id):
        calls.append((workspace_id, user_id))
        return f"\n\n--- CANVASES IN THIS DOCUMENT ---\n(canvases of {workspace_id})"

    monkeypatch.setattr(ai_routes, "document_canvases_text", fake)
    return calls


class TestLuminaReadsTheCanvases:
    def test_of_the_document_open_in_the_editor(self, chat_app, canvases):  # noqa: F811
        client, repos = chat_app
        repos.ws.get_by_id_and_user.return_value = SimpleNamespace(id="ws-1")

        res = client.post(
            "/ai/chat",
            json={"messages": MESSAGES, "workspaceId": "ws-1", "document_context": "# Doc"},
        )

        assert res.status_code == 200
        assert canvases == [("ws-1", "user-1")]
        assert "(canvases of ws-1)" in repos.streamed["context"].text

    def test_when_the_editor_thread_goes_on(self, chat_app, canvases):  # noqa: F811
        client, repos = chat_app
        # Only the first message names the document; the thread remembers it
        repos.conv.get_by_id.return_value = SimpleNamespace(
            id="conv-1", userId="user-1", workspaceId="ws-1"
        )

        client.post(
            "/ai/chat",
            json={"messages": MESSAGES, "conversationId": "conv-1", "document_context": "# Doc"},
        )

        assert canvases == [("ws-1", "user-1")]

    def test_of_a_document_picked_as_chat_context(self, chat_app, canvases):  # noqa: F811
        client, repos = chat_app
        repos.ws.get_by_id_and_user = AsyncMock(
            return_value=SimpleNamespace(
                id="ws-2", title="Launch", content="Notes", taskId=None
            )
        )

        client.post(
            "/ai/chat",
            json={"messages": MESSAGES, "contextType": "workspace", "contextId": "ws-2"},
        )

        assert canvases == [("ws-2", "user-1")]
        context = repos.streamed["context"].text
        # After the document itself
        assert context.index("Title: Launch") < context.index("(canvases of ws-2)")

    def test_not_of_someone_elses_document(self, chat_app, canvases):  # noqa: F811
        client, repos = chat_app
        repos.ws.get_by_id_and_user = AsyncMock(return_value=None)

        client.post(
            "/ai/chat",
            json={"messages": MESSAGES, "contextType": "workspace", "contextId": "ws-x"},
        )

        assert canvases == []

    def test_not_in_a_plain_chat(self, chat_app, canvases):  # noqa: F811
        client, _ = chat_app
        client.post("/ai/chat", json={"messages": MESSAGES})
        assert canvases == []
