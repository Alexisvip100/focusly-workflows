"""Only the owner of a canvas can see or change it, through every operation
the API has for canvases.

Someone else asking for it gets exactly the answer a canvas that doesn't
exist would give (so ids can't be probed), nothing about it changes, and no
link to its storage is handed out. A new canvas operation without an entry
here fails test_every_canvas_operation_is_covered."""

import time
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.config import settings
from app.database import Base
from app.graphql import schema
from app.models import Canvas, ProjectGroup, Workspace
from app.modules.canvas.services import canvas_files, canvas_service

OWNER, INTRUDER = "owner", "intruder"
SCENE = {
    "elements": [{"id": "el-1", "type": "rectangle"}],
    "appState": {},
    "files": {"img1": {"mimeType": "image/png", "created": 1}},
}


@pytest.fixture
async def session(monkeypatch):
    from app.modules.workspace.infrastructure.persistence import repository

    monkeypatch.setattr(repository, "cache", AsyncMock(get=AsyncMock(return_value=None)))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add_all(
            [
                ProjectGroup(id="owner-folder", userId=OWNER, name="Folder"),
                Workspace(
                    id="owner-doc", userId=OWNER, groupId="owner-folder",
                    title="Doc", content="",
                ),
                Workspace(id="intruder-doc", userId=INTRUDER, title="Mine", content=""),
                Canvas(
                    id="owner-canvas", userId=OWNER, workspaceId="owner-doc",
                    name="Private plan", icon="🔒", data=SCENE,
                ),
            ]
        )
        await s.commit()
        yield s
    await engine.dispose()


@pytest.fixture
def storage(monkeypatch):
    """Every way the API reaches the bucket, recorded."""
    signer = MagicMock()
    signer.generate_presigned_url.side_effect = (
        lambda op, Params, ExpiresIn: f"https://bucket.test/{Params['Key']}?sig"
    )
    deleter = MagicMock()
    monkeypatch.setattr(canvas_files, "s3_public_client", signer)
    monkeypatch.setattr(canvas_files, "s3_client", deleter)
    # Deletions run through the service's own reference too
    monkeypatch.setattr(canvas_service, "delete_canvas_files", MagicMock())
    monkeypatch.setattr(canvas_service, "delete_canvas_preview", MagicMock())
    return signer, deleter


async def run(session, query, user_id, **variables):
    return await schema.execute(
        query, variable_values=variables, context_value={"db": session, "user_id": user_id}
    )


# Each canvas operation, aimed at a canvas (or a document) by id
OPERATIONS = {
    "canvas": ("query Q($id: ID!) { canvas(id: $id) { id name data } }", "id"),
    "canvasFiles": (
        "query Q($id: ID!) { canvasFiles(canvasId: $id) { id url } }",
        "id",
    ),
    "updateCanvas": (
        "mutation M($id: ID!) { updateCanvas(input: {id: $id, name: \"Mine now\", "
        "icon: \"😈\", data: {elements: [], appState: {}}}) { id } }",
        "id",
    ),
    "removeCanvas": ("mutation M($id: ID!) { removeCanvas(id: $id) }", "id"),
    "createCanvasFileUpload": (
        "mutation M($id: ID!) { createCanvasFileUpload(input: {canvasId: $id, "
        "fileId: \"img1\", mimeType: \"image/png\", size: 10}) { uploadUrl } }",
        "id",
    ),
    "createCanvasPreviewUpload": (
        "mutation M($id: ID!) { createCanvasPreviewUpload(input: {canvasId: $id, "
        "mimeType: \"image/png\", size: 10}) { uploadUrl } }",
        "id",
    ),
    "removeCanvasPreview": (
        "mutation M($id: ID!) { removeCanvasPreview(canvasId: $id) }",
        "id",
    ),
    # Aimed at a document: a canvas can't be put in someone else's
    "createCanvas": (
        "mutation M($id: String!) { createCanvas(input: {name: \"Planted\", "
        "workspaceId: $id}) { id } }",
        "document",
    ),
    "canvasesByWorkspace": (
        "query Q($id: ID!) { canvasesByWorkspace(workspaceId: $id) { id name previewUrl } }",
        "document",
    ),
}


def target(op, *, exists=True):
    kind = OPERATIONS[op][1]
    if kind == "document":
        return "owner-doc" if exists else "no-such-doc"
    return "owner-canvas" if exists else "no-such-canvas"


def answer(result, *ids):
    """What a request got back, with the ids it asked about blanked out."""
    errors = [e.message for e in result.errors or []]
    text = repr((result.data, errors))
    for i in ids:
        text = text.replace(i, "<id>")
    return text


async def owner_view(session):
    session.expire_all()
    canvas = await session.get(Canvas, "owner-canvas")
    return {
        "name": canvas.name,
        "icon": canvas.icon,
        "data": canvas.data,
        "previewAt": canvas.previewAt,
        "count": len(
            (await run(session, OPERATIONS["canvasesByWorkspace"][0], OWNER, id="owner-doc"))
            .data["canvasesByWorkspace"]
        ),
    }


def test_every_canvas_operation_is_covered():
    # The names clients call, as the served schema has them
    served = schema._schema
    names = {*served.query_type.fields, *served.mutation_type.fields}
    canvas_ops = {n for n in names if "anvas" in n}
    assert canvas_ops == set(OPERATIONS), (
        "Add each new canvas operation to OPERATIONS, with how to aim it at "
        f"someone else's canvas: {sorted(canvas_ops ^ set(OPERATIONS))}"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("op", sorted(OPERATIONS))
async def test_someone_else_gets_what_a_missing_canvas_would_give(session, storage, op):
    query, _ = OPERATIONS[op]
    signer, _ = storage
    before = await owner_view(session)

    intruding = await run(session, query, INTRUDER, id=target(op))
    missing = await run(session, query, INTRUDER, id=target(op, exists=False))

    # The same answer as for an id that doesn't exist: nothing to tell them apart
    assert answer(intruding, target(op)) == answer(missing, target(op, exists=False))
    # And nothing of the owner's in it
    assert "Private plan" not in repr(intruding.data)
    assert "owner-canvas" not in repr(intruding.data)

    # The canvas is as it was, and the bucket was never asked for it
    assert await owner_view(session) == before
    signed_keys = [c.kwargs["Params"]["Key"] for c in signer.generate_presigned_url.call_args_list]
    assert not [k for k in signed_keys if "owner-canvas" in k or f"/{OWNER}/" in k]
    canvas_service.delete_canvas_files.assert_not_called()
    canvas_service.delete_canvas_preview.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("op", sorted(OPERATIONS))
async def test_nobody_signed_in_gets_anything(session, storage, op):
    query, _ = OPERATIONS[op]
    signer, _ = storage
    before = await owner_view(session)

    result = await run(session, query, None, id=target(op))

    assert result.data is None
    assert "Unauthorized" in result.errors[0].message
    assert await owner_view(session) == before
    signer.generate_presigned_url.assert_not_called()


@pytest.mark.anyio
async def test_the_owner_still_reaches_it_through_every_read(session, storage):
    """The checks above fail closed for the right reason: the same requests
    work for the owner."""
    got = await run(session, OPERATIONS["canvas"][0], OWNER, id="owner-canvas")
    assert got.data["canvas"]["name"] == "Private plan"
    files = await run(session, OPERATIONS["canvasFiles"][0], OWNER, id="owner-canvas")
    assert files.data["canvasFiles"][0]["url"].startswith(
        f"https://bucket.test/canvas/{OWNER}/owner-canvas/img1"
    )
    listed = await run(session, OPERATIONS["canvasesByWorkspace"][0], OWNER, id="owner-doc")
    assert [c["id"] for c in listed.data["canvasesByWorkspace"]] == ["owner-canvas"]


@pytest.mark.anyio
async def test_uploads_only_ever_land_in_the_requesters_own_folder(session, storage):
    signer, _ = storage
    mine = await run(
        session,
        "mutation { createCanvas(input: {name: \"Mine\", workspaceId: \"intruder-doc\"}) { id } }",
        INTRUDER,
    )
    my_canvas = mine.data["createCanvas"]["id"]
    for op in ("createCanvasFileUpload", "createCanvasPreviewUpload"):
        result = await run(session, OPERATIONS[op][0], INTRUDER, id=my_canvas)
        assert result.errors is None
    for call in signer.generate_presigned_url.call_args_list:
        assert call.kwargs["Params"]["Key"].startswith(f"canvas/{INTRUDER}/{my_canvas}/")


# ── Who the request is from ─────────────────────────────────────────────────


def request_with(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/graphql",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


def token(secret: str = settings.JWT_SECRET, **claims) -> str:
    payload = {"sub": OWNER, "type": "access", "exp": int(time.time()) + 60, **claims}
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers, expected",
    [
        ({"Authorization": f"Bearer {token()}"}, OWNER),
        ({}, None),
        (
            {"Authorization": f"Bearer {token(secret='not-the-servers-secret')}"},  # noqa: S106 (fake)
            None,
        ),
        ({"Authorization": f"Bearer {token(exp=int(time.time()) - 10)}"}, None),
        ({"Authorization": "Bearer not-a-token"}, None),
        # The week-long refresh token only renews the session
        ({"Authorization": f"Bearer {token(type='refresh')}"}, None),
        # A magic-link token (no subject) isn't a session
        (
            {"Authorization": f"Bearer {jwt.encode({'email': 'a@b.c', 'purpose': 'magic-link', 'exp': int(time.time()) + 60}, settings.JWT_SECRET, algorithm='HS256')}"},
            None,
        ),
        # Unsigned tokens ("alg": "none") are refused
        (
            {"Authorization": f"Bearer {jwt.encode({'sub': OWNER}, key=None, algorithm='none')}"},
            None,
        ),
    ],
    ids=["valid", "none", "other-secret", "expired", "garbage", "refresh", "magic-link", "unsigned"],
)
async def test_only_a_valid_session_token_names_a_user(headers, expected):
    from app.main import get_context

    context = await get_context(request_with(headers))
    assert context["user_id"] == expected
