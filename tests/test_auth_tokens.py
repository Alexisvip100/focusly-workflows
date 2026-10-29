"""A session's two tokens can't stand in for each other: the access token
calls the API, the refresh token only gets new tokens."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import HTTPException
from socketio.exceptions import ConnectionRefusedError
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.modules.auth.routes import refresh
from app.modules.auth.services.auth_service import AuthService
from app.modules.auth.tokens import (
    ACCESS,
    ACCESS_TOKEN_SECONDS,
    REFRESH,
    REFRESH_TOKEN_SECONDS,
    session_user_id,
)
from app.routes.common import get_current_user_id
from app.sockets.realtime import connect

USER = SimpleNamespace(
    id="user-1", email="a@b.c", role="user", name=None, picture=None, bio=None,
    authProvider="email", subscriptionStatus="free", settings=None, fcmToken=None,
    termsVersion=None, termsAcceptedAt=None, createdAt=None, updatedAt=None,
)


@pytest.fixture
def session_tokens():
    tokens = AuthService(MagicMock()).generate_jwt(USER)
    return tokens["access_token"], tokens["refresh_token"]


def claims(token):
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])


def signed(**payload):
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def request_with(headers=None, cookies=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


# ── The tokens ───────────────────────────────────────────────────────────────


def test_each_token_says_what_it_is_and_lasts_its_time(session_tokens):
    access, refresh_token = session_tokens
    a, r = claims(access), claims(refresh_token)
    assert (a["type"], a["sub"]) == (ACCESS, "user-1")
    assert (r["type"], r["sub"]) == (REFRESH, "user-1")
    assert a["exp"] - a["iat"] == ACCESS_TOKEN_SECONDS
    assert r["exp"] - r["iat"] == REFRESH_TOKEN_SECONDS


def test_a_token_is_only_good_for_its_own_use(session_tokens):
    access, refresh_token = session_tokens
    assert session_user_id(access, ACCESS) == "user-1"
    assert session_user_id(refresh_token, REFRESH) == "user-1"
    with pytest.raises(jwt.InvalidTokenError):
        session_user_id(refresh_token, ACCESS)
    with pytest.raises(jwt.InvalidTokenError):
        session_user_id(access, REFRESH)


def test_tokens_from_before_their_type_are_told_apart_by_lifetime():
    now = int(time.time())
    old_access = signed(sub="user-1", iat=now, exp=now + ACCESS_TOKEN_SECONDS)
    old_refresh = signed(sub="user-1", iat=now, exp=now + REFRESH_TOKEN_SECONDS)
    assert session_user_id(old_access, ACCESS) == "user-1"
    assert session_user_id(old_refresh, REFRESH) == "user-1"
    with pytest.raises(jwt.InvalidTokenError):
        session_user_id(old_refresh, ACCESS)
    with pytest.raises(jwt.InvalidTokenError):
        session_user_id(old_access, REFRESH)


@pytest.mark.parametrize(
    "token, error",
    [
        (signed(sub="user-1", type=ACCESS, exp=int(time.time()) - 5), jwt.ExpiredSignatureError),
        (signed(type=ACCESS, exp=int(time.time()) + 60), jwt.InvalidTokenError),
        (
            jwt.encode(
                {"sub": "user-1", "type": ACCESS, "exp": int(time.time()) + 60},
                "another-secret",  # noqa: S105 (fake)
                algorithm="HS256",
            ),
            jwt.InvalidTokenError,
        ),
        (signed(email="a@b.c", purpose="magic-link", exp=int(time.time()) + 60), jwt.InvalidTokenError),
    ],
    ids=["expired", "no-subject", "other-secret", "magic-link"],
)
def test_what_isnt_a_session_token_is_refused(token, error):
    with pytest.raises(error):
        session_user_id(token, ACCESS)


# ── Where they're used ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_the_api_takes_only_the_access_token(session_tokens):
    access, refresh_token = session_tokens
    assert await get_current_user_id(request_with({"Authorization": f"Bearer {access}"})) == "user-1"
    with pytest.raises(HTTPException) as refused:
        await get_current_user_id(request_with({"Authorization": f"Bearer {refresh_token}"}))
    assert refused.value.status_code == 401


@pytest.mark.anyio
async def test_the_realtime_socket_takes_only_the_access_token(session_tokens, monkeypatch):
    from app.sockets import realtime

    enter_room = AsyncMock()
    monkeypatch.setattr(realtime.sio, "enter_room", enter_room)
    access, refresh_token = session_tokens

    await connect("sid-1", {}, {"token": access})
    enter_room.assert_awaited_once_with("sid-1", "user_user-1", namespace="/realtime")
    with pytest.raises(ConnectionRefusedError):
        await connect("sid-2", {}, {"token": refresh_token})


@pytest.mark.anyio
async def test_only_the_refresh_token_renews_the_session(session_tokens):
    access, refresh_token = session_tokens
    service = MagicMock(refresh_session=AsyncMock(return_value=USER))
    service.generate_jwt.return_value = {"access_token": "new-a", "refresh_token": "new-r"}

    renewed = await refresh(request_with(cookies={"refresh_token": refresh_token}), Response(), service)
    assert renewed == {"success": True}
    service.refresh_session.assert_awaited_once_with("user-1")

    # A stolen 15-minute access token can't be traded for a week-long session
    service.refresh_session.reset_mock()
    with pytest.raises(HTTPException) as refused:
        await refresh(request_with(cookies={"refresh_token": access}), Response(), service)
    assert refused.value.status_code == 401
    service.refresh_session.assert_not_awaited()
