"""Loading the calendar after connecting Google: the events come straight
from Google, and the sync runs behind the response, at most once a minute.
It used to run inline on every load and, since Google events aren't stored
as tasks, always as a full re-read of the calendar (minutes, then the
browser gave up)."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.auth.services import auth_service as auth_module
from app.modules.auth.services.auth_service import AuthService
from app.modules.google_calendar import routes
from app.modules.google_calendar.services import (
    google_calendar_service as gc_module,
)
from app.modules.google_calendar.services.google_calendar_service import (
    GoogleCalendarService,
)


def _event(event_id: str, **over) -> dict:
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": f"Evento {event_id}",
        "etag": f'"{event_id}-1"',
        "start": {"dateTime": "2026-10-14T15:00:00Z"},
        "end": {"dateTime": "2026-10-14T16:00:00Z"},
        **over,
    }


# ── GET /google-calendar/events ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_events_answer_without_waiting_for_the_sync(monkeypatch):
    user = SimpleNamespace(id="u1", email="yo@example.com", googleRefreshToken="r")
    monkeypatch.setattr(
        routes,
        "UsersRepository",
        lambda db: SimpleNamespace(get_by_id=AsyncMock(return_value=user)),
    )
    started = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "start_background_sync", started)

    gc = GoogleCalendarService(db=MagicMock())
    gc.sync_calendar = AsyncMock(side_effect=AssertionError("not inline"))
    gc.get_events = AsyncMock(
        return_value={"items": [_event("a"), _event("b", status="cancelled")]}
    )

    events = await routes.get_events(
        timeMin="2026-09-24T06:00:00.000Z",
        timeMax="2026-11-08T05:59:59.999Z",
        user_id="u1",
        gc_service=gc,
    )

    started.assert_awaited_once_with("u1")
    gc.get_events.assert_awaited_once_with(
        "u1", time_min="2026-09-24T06:00:00.000Z", time_max="2026-11-08T05:59:59.999Z"
    )
    assert [e["google_event_id"] for e in events] == ["a"]


@pytest.mark.anyio
async def test_without_google_connected_nothing_is_synced(monkeypatch):
    user = SimpleNamespace(id="u1", googleRefreshToken=None)
    monkeypatch.setattr(
        routes,
        "UsersRepository",
        lambda db: SimpleNamespace(get_by_id=AsyncMock(return_value=user)),
    )
    started = AsyncMock()
    monkeypatch.setattr(routes, "start_background_sync", started)

    assert await routes.get_events(user_id="u1", gc_service=MagicMock()) == []
    started.assert_not_awaited()


# ── The background sync ─────────────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize(
    "lock, throttle, runs",
    [
        (True, True, True),
        (False, True, False),
        (None, True, True),
        (False, False, True),
    ],
    ids=["first load", "loaded again within a minute", "redis down", "webhook"],
)
async def test_one_sync_per_user_per_minute_except_webhooks(
    monkeypatch, lock, throttle, runs
):
    acquire = AsyncMock(return_value=lock)
    monkeypatch.setattr(routes.cache, "acquire_lock", acquire)
    synced = []

    async def fake_sync(user_id, notify):
        synced.append((user_id, notify))

    monkeypatch.setattr(routes, "_sync_in_background", fake_sync)

    started = await routes.start_background_sync(
        "u1", notify=not throttle, throttle=throttle
    )
    await asyncio.sleep(0)

    assert started is runs
    assert synced == ([("u1", not throttle)] if runs else [])
    if throttle:
        acquire.assert_awaited_once_with("gcal:sync:u1", routes.SYNC_THROTTLE_SECONDS)
    else:
        acquire.assert_not_awaited()


@pytest.mark.anyio
async def test_a_failed_background_sync_is_logged_not_raised(monkeypatch, caplog):
    class Session:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    import app.database

    monkeypatch.setattr(app.database, "async_session_local", lambda: Session())
    gc = MagicMock()
    gc.sync_calendar = AsyncMock(side_effect=ValueError("token revoked"))
    monkeypatch.setattr(routes, "build_google_calendar_service", lambda db: gc)

    await routes._sync_in_background("u1", notify=True)

    assert "token revoked" in caplog.text


# ── sync_calendar ───────────────────────────────────────────────────────────


class _FakeHttp:
    """Google's events list: answers the pages in order, records the URLs."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.urls = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        self.urls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: self.pages.pop(0))


def _sync_world(monkeypatch, *, sync_token, linked, pages):
    user = SimpleNamespace(
        id="u1", email="yo@example.com", googleCalendarSyncToken=sync_token
    )
    users_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=user), save=AsyncMock()
    )
    tasks_repo = SimpleNamespace(
        delete_google_tasks_by_user=AsyncMock(return_value=0),
        get_all_active_by_user=AsyncMock(return_value=linked),
        get_by_google_event_id=AsyncMock(
            side_effect=AssertionError("one query per event")
        ),
    )
    http = _FakeHttp(pages)
    monkeypatch.setattr(gc_module, "UsersRepository", lambda db: users_repo)
    monkeypatch.setattr(gc_module, "TasksRepository", lambda db: tasks_repo)
    monkeypatch.setattr(gc_module.httpx, "AsyncClient", http)

    tasks_service = MagicMock()
    tasks_service.create = AsyncMock(return_value={"_changed": True})
    tasks_service.delete = AsyncMock()
    tasks_service.socket_server = None
    gc = GoogleCalendarService(
        db=MagicMock(),
        auth_service=SimpleNamespace(
            refresh_google_access_token=AsyncMock(return_value={"access_token": "x"})
        ),
        tasks_service=tasks_service,
        scheduler_service=SimpleNamespace(run_scheduling_pipeline=AsyncMock()),
    )
    gc.watch_calendar = AsyncMock()
    return SimpleNamespace(gc=gc, user=user, http=http, tasks=tasks_service)


@pytest.mark.anyio
async def test_with_no_linked_tasks_the_sync_stays_incremental(monkeypatch):
    world = _sync_world(
        monkeypatch,
        sync_token="tok-1",  # noqa: S106 - a fake sync token
        linked=[],
        pages=[{"items": [_event("a")], "nextSyncToken": "tok-2"}],
    )

    await world.gc.sync_calendar("u1")

    params = parse_qs(urlparse(world.http.urls[0]).query)
    assert params["syncToken"] == ["tok-1"]
    assert "timeMin" not in params
    assert world.user.googleCalendarSyncToken == "tok-2"
    world.tasks.create.assert_not_awaited()  # Google's own events: not stored


@pytest.mark.anyio
async def test_linked_tasks_follow_their_google_event(monkeypatch):
    moved = SimpleNamespace(
        id="t1", google_event_id="a", source="platform", google_synced_etag="old"
    )
    gone = SimpleNamespace(id="t2", google_event_id="b", source="platform")
    unlinked = SimpleNamespace(id="t3", google_event_id=None, source="platform")
    world = _sync_world(
        monkeypatch,
        sync_token=None,
        linked=[moved, gone, unlinked],
        pages=[
            {"items": [_event("a")], "nextPageToken": "p2"},
            {
                "items": [_event("b", status="cancelled"), _event("other")],
                "nextSyncToken": "tok-1",
            },
        ],
    )

    await world.gc.sync_calendar("u1")

    assert len(world.http.urls) == 2  # both pages
    world.tasks.delete.assert_awaited_once_with(
        "t2", skip_scheduling=True, skip_google_sync=True
    )
    created = world.tasks.create.await_args.args[0]
    assert created["google_event_id"] == "a"
    assert "estimated_start_date" in created  # a real edit on Google: dates move
    assert world.user.googleCalendarSyncToken == "tok-1"
    world.gc.scheduler_service.run_scheduling_pipeline.assert_awaited_once()


# ── The Google access token ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_the_access_token_is_reused_until_it_expires(monkeypatch):
    store: dict = {}

    async def get(key):
        return store.get(key)

    async def set_(key, value, expire_seconds=3600):
        store[key] = value
        return True

    monkeypatch.setattr(auth_module.cache, "get", get)
    monkeypatch.setattr(auth_module.cache, "set", set_)

    user = SimpleNamespace(id="u1", googleRefreshToken="refresh-1")
    monkeypatch.setattr(
        auth_module,
        "UsersRepository",
        lambda db: SimpleNamespace(get_by_id=AsyncMock(return_value=user)),
    )
    posts = []

    class Http:
        def __call__(self, *a, **k):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None):
            posts.append(data["refresh_token"])
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "access_token": f"access-{len(posts)}",
                    "expires_in": 3599,
                },
            )

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", Http())
    auth = AuthService(MagicMock())

    first = await auth.refresh_google_access_token("u1")
    second = await auth.refresh_google_access_token("u1")
    assert first["access_token"] == second["access_token"] == "access-1"  # noqa: S105
    assert posts == ["refresh-1"]
    assert first["expiry_date"] > time.time() * 1000

    # Google connected again: a new refresh token never reuses the old entry.
    user.googleRefreshToken = "refresh-2"
    third = await auth.refresh_google_access_token("u1")
    assert third["access_token"] == "access-2"  # noqa: S105
    assert posts == ["refresh-1", "refresh-2"]
    assert all("refresh" not in k for k in store)  # the token isn't in the key
