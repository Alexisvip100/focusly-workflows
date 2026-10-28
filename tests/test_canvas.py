from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.graphql import schema
from app.models import ProjectGroup, Workspace
from app.modules.canvas.schemas.canvas import MAX_CANVAS_DATA_BYTES
from app.modules.canvas.services.canvas_service import CanvasService
from app.modules.workspace.services.project_groups_service import ProjectGroupsService
from app.modules.workspace.services.workspaces_service import WorkspacesService

SCENE = {"elements": [{"id": "el-1", "type": "rectangle"}], "appState": {}}


# ── Service (real SQLite database) ───────────────────────────────────────────


@pytest.fixture
async def session(monkeypatch):
    # The workspace repositories cache through Redis; keep the tests off it.
    from app.modules.workspace.infrastructure.persistence import repository

    monkeypatch.setattr(repository, "cache", AsyncMock(get=AsyncMock(return_value=None)))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all(
            [
                ProjectGroup(id="group-1", userId="user-1", name="Folder"),
                Workspace(
                    id="ws-1", userId="user-1", groupId="group-1", title="Doc", content=""
                ),
                Workspace(id="ws-2", userId="user-2", title="Other's doc", content=""),
            ]
        )
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.anyio
async def test_create_and_read_back_a_scene(session):
    service = CanvasService(session)
    created = await service.create(
        {"name": "Ideas", "workspaceId": "ws-1", "data": SCENE}, "user-1"
    )
    found = await service.find_one(created.id, "user-1")
    assert found.data == SCENE
    assert [c.id for c in await service.find_by_workspace("ws-1", "user-1")] == [
        created.id
    ]


@pytest.mark.anyio
async def test_a_document_can_hold_several_canvases(session):
    service = CanvasService(session)
    await service.create({"name": "A", "workspaceId": "ws-1"}, "user-1")
    await service.create({"name": "B", "workspaceId": "ws-1"}, "user-1")
    assert len(await service.find_by_workspace("ws-1", "user-1")) == 2


@pytest.mark.anyio
async def test_cannot_create_a_canvas_in_someone_elses_document(session):
    with pytest.raises(ValueError, match="not found"):
        await CanvasService(session).create(
            {"name": "Ideas", "workspaceId": "ws-2"}, "user-1"
        )


@pytest.mark.anyio
async def test_update_replaces_the_scene_and_keeps_the_name(session):
    service = CanvasService(session)
    created = await service.create({"name": "Ideas", "workspaceId": "ws-1"}, "user-1")
    new_scene = {"elements": [{"id": "el-2", "type": "ellipse"}], "appState": {}}

    await service.update(created.id, {"data": new_scene}, "user-1")

    found = await service.find_one(created.id, "user-1")
    assert found.data == new_scene
    assert found.name == "Ideas"


@pytest.mark.anyio
async def test_other_users_cannot_read_update_or_delete_it(session):
    service = CanvasService(session)
    created = await service.create({"name": "Ideas", "workspaceId": "ws-1"}, "user-1")
    for attempt in (
        service.find_one(created.id, "user-2"),
        service.update(created.id, {"name": "Mine now"}, "user-2"),
        service.remove(created.id, "user-2"),
    ):
        with pytest.raises(ValueError, match="not found"):
            await attempt
    assert await service.find_by_workspace("ws-1", "user-2") == []


@pytest.mark.anyio
async def test_deleting_the_document_deletes_its_canvases(session):
    service = CanvasService(session)
    created = await service.create({"name": "Ideas", "workspaceId": "ws-1"}, "user-1")

    await WorkspacesService(session).remove("ws-1", "user-1")

    with pytest.raises(ValueError):
        await service.find_one(created.id, "user-1")


@pytest.mark.anyio
async def test_deleting_the_folder_deletes_its_documents_canvases(session):
    service = CanvasService(session)
    created = await service.create({"name": "Ideas", "workspaceId": "ws-1"}, "user-1")

    await ProjectGroupsService(session).remove("group-1", "user-1")

    with pytest.raises(ValueError):
        await service.find_one(created.id, "user-1")


@pytest.mark.anyio
async def test_oversized_scenes_are_rejected(session):
    huge = {"elements": [{"text": "x" * MAX_CANVAS_DATA_BYTES}], "appState": {}}
    with pytest.raises(ValidationError, match="too large"):
        await CanvasService(session).create({"name": "Big", "data": huge}, "user-1")


# ── GraphQL (real SQLite database) ───────────────────────────────────────────

CREATE = """
mutation Create($input: CreateCanvasInput!) {
  createCanvas(input: $input) { id name workspaceId data }
}
"""
UPDATE = """
mutation Update($input: UpdateCanvasInput!) {
  updateCanvas(input: $input) { id name data }
}
"""
GET = "query Get($id: ID!) { canvas(id: $id) { id name data } }"
LIST = "query List($ws: ID!) { canvasesByWorkspace(workspaceId: $ws) { id name data } }"
REMOVE = "mutation Remove($id: ID!) { removeCanvas(id: $id) }"


async def run(session, query, user_id="user-1", **variables):
    return await schema.execute(
        query,
        variable_values=variables,
        context_value={"db": session, "user_id": user_id},
    )


@pytest.mark.anyio
async def test_graphql_create_then_autosave_then_read_back(session):
    created = await run(
        session, CREATE, input={"name": "Ideas", "workspaceId": "ws-1", "data": SCENE}
    )
    assert created.errors is None
    canvas = created.data["createCanvas"]
    assert canvas["workspaceId"] == "ws-1"
    assert canvas["data"] == SCENE

    new_scene = {"elements": [{"id": "el-2", "type": "ellipse"}], "appState": {}}
    saved = await run(session, UPDATE, input={"id": canvas["id"], "data": new_scene})
    assert saved.errors is None
    # The autosave doesn't echo the scene back
    assert saved.data["updateCanvas"]["data"] is None

    read = await run(session, GET, id=canvas["id"])
    assert read.data["canvas"] == {"id": canvas["id"], "name": "Ideas", "data": new_scene}


@pytest.mark.anyio
async def test_graphql_list_leaves_out_the_scenes(session):
    await run(session, CREATE, input={"name": "Ideas", "workspaceId": "ws-1", "data": SCENE})
    listed = await run(session, LIST, ws="ws-1")
    assert listed.errors is None
    assert [c["data"] for c in listed.data["canvasesByWorkspace"]] == [None]


@pytest.mark.anyio
async def test_graphql_hides_canvases_from_other_users(session):
    created = await run(session, CREATE, input={"name": "Ideas", "workspaceId": "ws-1"})
    canvas_id = created.data["createCanvas"]["id"]

    for query, variables in (
        (GET, {"id": canvas_id}),
        (UPDATE, {"input": {"id": canvas_id, "name": "Mine now"}}),
        (REMOVE, {"id": canvas_id}),
    ):
        result = await run(session, query, user_id="user-2", **variables)
        assert result.data is None
        assert "not found" in str(result.errors[0])

    assert (await run(session, GET, id=canvas_id)).data["canvas"]["name"] == "Ideas"


@pytest.mark.anyio
async def test_graphql_requires_a_signed_in_user(session):
    result = await run(session, GET, user_id=None, id="canvas-1")
    assert "Unauthorized" in str(result.errors[0])


@pytest.mark.anyio
async def test_graphql_remove(session):
    created = await run(session, CREATE, input={"name": "Ideas", "workspaceId": "ws-1"})
    canvas_id = created.data["createCanvas"]["id"]

    removed = await run(session, REMOVE, id=canvas_id)
    assert removed.data == {"removeCanvas": True}
    assert (await run(session, GET, id=canvas_id)).data is None


@pytest.mark.anyio
async def test_graphql_icon_is_set_and_changed_apart_from_the_name(session):
    created = await run(
        session,
        "mutation C($input: CreateCanvasInput!) { createCanvas(input: $input) { id icon } }",
        input={"name": "Ideas", "workspaceId": "ws-1"},
    )
    canvas_id = created.data["createCanvas"]["id"]
    assert created.data["createCanvas"]["icon"] is None

    changed = await run(
        session,
        "mutation U($input: UpdateCanvasInput!) { updateCanvas(input: $input) { name icon } }",
        input={"id": canvas_id, "icon": "🧠"},
    )
    assert changed.errors is None
    assert changed.data["updateCanvas"] == {"name": "Ideas", "icon": "🧠"}


@pytest.mark.anyio
async def test_graphql_rejects_an_icon_that_is_not_one_emoji(session):
    created = await run(session, CREATE, input={"name": "Ideas", "workspaceId": "ws-1"})
    result = await run(
        session,
        UPDATE,
        input={"id": created.data["createCanvas"]["id"], "icon": "x" * 100},
    )
    assert result.data is None


# ── Images pasted into a canvas ──────────────────────────────────────────────

import boto3
from botocore.client import Config
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from app.modules.canvas.services import canvas_files

UPLOAD = """
mutation U($input: CreateCanvasFileUploadInput!) {
  createCanvasFileUpload(input: $input) { uploadUrl }
}
"""
FILES = "query F($id: ID!) { canvasFiles(canvasId: $id) { id mimeType url } }"


@pytest.fixture
def signer(monkeypatch):
    """A real S3 signer with test credentials: links are signed offline."""
    client = boto3.client(
        "s3",
        endpoint_url="http://storage.test:9000",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106 (fake: signs offline)
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    monkeypatch.setattr(canvas_files, "s3_public_client", client)
    return client


async def new_canvas(session, user_id="user-1"):
    created = await run(
        session, CREATE, user_id=user_id, input={"name": "Ideas", "workspaceId": "ws-1"}
    )
    return created.data["createCanvas"]["id"]


@pytest.mark.anyio
async def test_upload_link_is_signed_for_the_exact_type_and_size(session, signer):
    canvas_id = await new_canvas(session)
    result = await run(
        session,
        UPLOAD,
        input={"canvasId": canvas_id, "fileId": "abc123", "mimeType": "image/png", "size": 2048},
    )
    assert result.errors is None
    url = urlparse(result.data["createCanvasFileUpload"]["uploadUrl"])
    assert url.path == f"/media/canvas/user-1/{canvas_id}/abc123" or url.path.endswith(
        f"/canvas/user-1/{canvas_id}/abc123"
    )
    signed = parse_qs(url.query)["X-Amz-SignedHeaders"][0].split(";")
    assert "content-length" in signed and "content-type" in signed


@pytest.mark.anyio
@pytest.mark.parametrize(
    "file_id, mime_type, size, message",
    [
        ("abc", "image/svg+xml", 100, "can't be saved"),
        ("abc", "application/pdf", 100, "can't be saved"),
        ("abc", "image/png", 11 * 1024 * 1024, "up to 10 MB"),
        ("abc", "image/png", 0, "up to 10 MB"),
        ("../other/key", "image/png", 100, "Invalid canvas file id"),
    ],
)
async def test_upload_link_refuses_what_a_canvas_cant_store(
    session, signer, file_id, mime_type, size, message
):
    canvas_id = await new_canvas(session)
    result = await run(
        session,
        UPLOAD,
        input={"canvasId": canvas_id, "fileId": file_id, "mimeType": mime_type, "size": size},
    )
    assert result.data is None
    assert message in str(result.errors[0])


@pytest.mark.anyio
async def test_only_the_owner_can_upload_or_read_a_canvas_images(session, signer):
    canvas_id = await new_canvas(session)
    upload = await run(
        session,
        UPLOAD,
        user_id="user-2",
        input={"canvasId": canvas_id, "fileId": "abc", "mimeType": "image/png", "size": 10},
    )
    read = await run(session, FILES, user_id="user-2", id=canvas_id)
    for result in (upload, read):
        assert result.data is None
        assert "not found" in str(result.errors[0])


@pytest.mark.anyio
async def test_reads_back_the_images_the_saved_scene_uses(session, signer):
    canvas_id = await new_canvas(session)
    scene = {
        "elements": [],
        "appState": {},
        "files": {
            "img1": {"mimeType": "image/png", "created": 1},
            "img2": {"mimeType": "image/jpeg", "created": 2},
            "../bad": {"mimeType": "image/png"},
        },
    }
    await run(session, UPDATE, input={"id": canvas_id, "data": scene})

    result = await run(session, FILES, id=canvas_id)
    assert result.errors is None
    files = {f["id"]: f for f in result.data["canvasFiles"]}
    assert set(files) == {"img1", "img2"}  # a malformed id is skipped
    assert files["img2"]["mimeType"] == "image/jpeg"
    assert f"canvas/user-1/{canvas_id}/img1" in files["img1"]["url"]
    assert "X-Amz-Signature" in files["img1"]["url"]


@pytest.mark.anyio
async def test_deleting_a_canvas_deletes_its_images(session):
    canvas_id = await new_canvas(session)
    with patch.object(
        __import__("app.modules.canvas.services.canvas_service", fromlist=["x"]),
        "delete_canvas_files",
    ) as delete_files:
        await run(session, REMOVE, id=canvas_id)
    delete_files.assert_called_once_with("user-1", canvas_id)


@pytest.mark.anyio
async def test_deleting_a_document_or_folder_deletes_its_canvases_images(session):
    first = await new_canvas(session)
    with patch(
        "app.modules.workspace.services.workspaces_service.delete_canvas_files"
    ) as delete_files:
        await WorkspacesService(session).remove("ws-1", "user-1")
    delete_files.assert_called_once_with("user-1", first)

    # A folder: its documents' canvases
    session.add(Workspace(id="ws-3", userId="user-1", groupId="group-1", title="D", content=""))
    await session.commit()
    second = (
        await CanvasService(session).create({"name": "B", "workspaceId": "ws-3"}, "user-1")
    ).id
    with patch(
        "app.modules.workspace.services.project_groups_service.delete_canvas_files"
    ) as delete_files:
        await ProjectGroupsService(session).remove("group-1", "user-1")
    delete_files.assert_called_once_with("user-1", second)
