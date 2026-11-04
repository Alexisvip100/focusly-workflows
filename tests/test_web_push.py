import base64
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pywebpush import WebPushException

import generate_vapid_keys
from app.config import settings
from app.database import get_db
from app.modules.notification import push_routes
from app.modules.notification.services import (
    morning_push_service,
    push_service,
    task_notifier_service,
)
from app.routes.common import get_current_user_id


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture
def vapid(monkeypatch):
    public, private = generate_vapid_keys.generate()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:test@focusly.app")
    return public, private


@pytest.fixture
def no_vapid(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")


def _sub(endpoint="https://push.example.com/abc", user_id="u1"):
    return SimpleNamespace(endpoint=endpoint, p256dh="p", auth="a", userId=user_id)


def _db_returning(subs):
    """A session whose first execute() lists `subs`; later ones are writes."""
    db = MagicMock()
    listing = MagicMock()
    listing.scalars.return_value.all.return_value = subs
    db.execute = AsyncMock(side_effect=[listing] + [MagicMock()] * 5)
    db.commit = AsyncMock()
    return db


# ─── Keys ───────────────────────────────────────────────────────────────────


def test_generated_keys_have_the_web_push_shapes():
    public, private = generate_vapid_keys.generate()
    raw_public = _b64url_decode(public)
    assert len(raw_public) == 65 and raw_public[0] == 0x04  # uncompressed P-256
    assert len(_b64url_decode(private)) == 32
    assert "=" not in public + private


def test_a_real_push_is_encrypted_for_the_browser_and_signed(vapid, monkeypatch):
    """End to end through pywebpush: the browser's keys decrypt the payload,
    and the VAPID header carries this server's public key."""
    public, _ = vapid
    browser_key = ec.generate_private_key(ec.SECP256R1())
    browser_public = browser_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth_secret = b"0123456789abcdef"
    sub = SimpleNamespace(
        endpoint="https://fcm.googleapis.com/fcm/send/xyz",
        p256dh=_b64url(browser_public),
        auth=_b64url(auth_secret),
        userId="u1",
    )
    sent = {}

    def fake_post(url, data=None, headers=None, timeout=None, **_):
        sent.update(url=url, data=data, headers=headers)
        return SimpleNamespace(status_code=201, text="", headers={})

    monkeypatch.setattr("pywebpush.requests.post", fake_post)

    payload = json.dumps({"title": "Bocetos", "body": "Empieza en 5 minutos"})
    assert push_service._send_one(sub, payload, ttl=60) is None

    assert sent["url"] == sub.endpoint
    assert sent["headers"]["ttl"] == "60"
    assert f"k={public}" in sent["headers"]["authorization"]
    plain = http_ece.decrypt(
        sent["data"], private_key=browser_key, auth_secret=auth_secret, version="aes128gcm"
    )
    assert json.loads(plain) == {"title": "Bocetos", "body": "Empieza en 5 minutos"}


# ─── Sending ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_send_is_a_no_op_without_keys(no_vapid, monkeypatch):
    send = MagicMock()
    monkeypatch.setattr(push_service, "_send_one", send)
    db = _db_returning([_sub()])
    assert await push_service.send_to_user(db, "u1", "t", "b") == 0
    send.assert_not_called()
    db.execute.assert_not_called()


@pytest.mark.anyio
async def test_send_reaches_every_device_and_forgets_the_gone_ones(vapid, monkeypatch):
    alive, gone, failing = (
        _sub("https://push.example.com/alive"),
        _sub("https://push.example.com/gone"),
        _sub("https://push.example.com/failing"),
    )
    results = {alive.endpoint: None, gone.endpoint: 410, failing.endpoint: 500}
    payloads = []

    def fake_send(sub, data, ttl):
        payloads.append(json.loads(data))
        return results[sub.endpoint]

    monkeypatch.setattr(push_service, "_send_one", fake_send)
    db = _db_returning([alive, gone, failing])

    delivered = await push_service.send_to_user(
        db, "u1", "Bocetos", "Empieza ahora", tag="task-1", renotify=True, in_app=True
    )

    assert delivered == 1
    assert payloads[0] == {
        "title": "Bocetos",
        "body": "Empieza ahora",
        "url": "/dashboard",
        "tag": "task-1",
        "renotify": True,
        "inApp": True,
    }
    # One delete, for the 410 only (a 500 may be temporary)
    delete_stmt = db.execute.await_args_list[1].args[0]
    assert "gone" in str(delete_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "failing" not in str(delete_stmt.compile(compile_kwargs={"literal_binds": True}))
    db.commit.assert_awaited()


@pytest.mark.anyio
async def test_send_with_no_devices_sends_nothing(vapid, monkeypatch):
    send = MagicMock()
    monkeypatch.setattr(push_service, "_send_one", send)
    assert await push_service.send_to_user(_db_returning([]), "u1", "t", "b") == 0
    send.assert_not_called()


def test_send_one_reports_the_push_services_refusal(vapid, monkeypatch):
    def refuse(**_):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410, text=""))

    monkeypatch.setattr(push_service, "webpush", refuse)
    assert push_service._send_one(_sub(), "{}", 60) == 410


def test_subject_falls_back_to_a_valid_contact(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
    assert push_service._subject().startswith("mailto:")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.focusly.com")
    assert push_service._subject() == "https://app.focusly.com"


# ─── Routes ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(push_routes.router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    saved = AsyncMock()
    removed = AsyncMock(return_value=True)
    monkeypatch.setattr(push_service, "save_subscription", saved)
    monkeypatch.setattr(push_service, "remove_subscription", removed)
    return app, saved, removed


SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/xyz",
    "keys": {"p256dh": "BPk", "auth": "c2Vj"},
}


def test_public_key_says_when_push_is_off(client, no_vapid):
    app, *_ = client
    body = TestClient(app).get("/push/public-key").json()
    assert body == {"enabled": False, "publicKey": None}


def test_public_key_is_served_when_configured(client, vapid):
    app, *_ = client
    body = TestClient(app).get("/push/public-key").json()
    assert body == {"enabled": True, "publicKey": vapid[0]}


def test_subscribing_needs_a_session(client, vapid):
    app, saved, _ = client
    response = TestClient(app).post("/push/subscriptions", json=SUBSCRIPTION)
    assert response.status_code == 401
    saved.assert_not_called()


def test_subscribe_stores_the_device_with_its_time_zone(client, vapid):
    app, saved, _ = client
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    response = TestClient(app).post(
        "/push/subscriptions",
        json={**SUBSCRIPTION, "timeZone": "America/Mexico_City"},
        headers={"user-agent": "Chrome"},
    )
    assert response.status_code == 200
    args = saved.await_args.args
    assert args[1:] == ("u1", SUBSCRIPTION["endpoint"], "BPk", "c2Vj", "Chrome", "America/Mexico_City")


def test_an_unknown_time_zone_is_dropped(client, vapid):
    app, saved, _ = client
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    TestClient(app).post("/push/subscriptions", json={**SUBSCRIPTION, "timeZone": "Mars/Olympus"})
    assert saved.await_args.args[-1] is None


def test_only_https_push_endpoints_are_accepted(client, vapid):
    app, saved, _ = client
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    response = TestClient(app).post(
        "/push/subscriptions", json={**SUBSCRIPTION, "endpoint": "http://evil.example/x"}
    )
    assert response.status_code == 400
    saved.assert_not_called()


def test_subscribe_is_refused_when_push_is_off(client, no_vapid):
    app, saved, _ = client
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    assert TestClient(app).post("/push/subscriptions", json=SUBSCRIPTION).status_code == 503
    saved.assert_not_called()


def test_unsubscribe_removes_only_the_callers_device(client, vapid):
    app, _, removed = client
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    response = TestClient(app).request(
        "DELETE", "/push/subscriptions", json={"endpoint": SUBSCRIPTION["endpoint"]}
    )
    assert response.json() == {"success": True, "removed": True}
    assert removed.await_args.args[1:] == ("u1", SUBSCRIPTION["endpoint"])


# ─── Task reminders ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "minutes, text",
    [(5, "Empieza en 5 minutos"), (1, "Empieza en 1 minuto"), (0, "Empieza ahora")],
)
def test_reminder_body(minutes, text):
    assert task_notifier_service.reminder_body(minutes) == text


@pytest.mark.anyio
async def test_each_reminder_is_pushed_after_the_commit(monkeypatch):
    now = datetime.utcnow()
    task = SimpleNamespace(
        id="t1", userId="u1", title="Bocetos", estimated_start_date=now, deadline=None
    )
    events = []

    tasks_repo = MagicMock()
    tasks_repo.get_tasks_for_warning = AsyncMock(side_effect=[[(task, None)], []])
    tasks_repo.save = AsyncMock()
    notif_repo = MagicMock()
    notif_repo.create = AsyncMock()
    db = MagicMock()
    db.commit = AsyncMock(side_effect=lambda: events.append("commit"))

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return False

    async def fake_push(_db, user_id, title, body, **kwargs):
        events.append(("push", user_id, title, body, kwargs["tag"], kwargs["in_app"]))
        return 1

    monkeypatch.setattr(task_notifier_service, "async_session_local", Session)
    monkeypatch.setattr(task_notifier_service, "TasksRepository", lambda _db: tasks_repo)
    monkeypatch.setattr(task_notifier_service, "NotificationsRepository", lambda _db: notif_repo)
    monkeypatch.setattr(task_notifier_service, "_emit_notification", AsyncMock())
    monkeypatch.setattr(task_notifier_service.push_service, "send_to_user", fake_push)

    await task_notifier_service._check_and_notify_once()

    assert events[0] == "commit"
    assert events[1] == ("push", "u1", "Bocetos", "Empieza ahora", "t1", True)


# ─── Morning summary ────────────────────────────────────────────────────────


def test_local_day_bounds_in_mexico_city():
    start, end = morning_push_service.local_day_bounds_utc(
        datetime(2026, 11, 4, 14, 0), ZoneInfo("America/Mexico_City")
    )
    assert (start, end) == (datetime(2026, 11, 4, 6, 0), datetime(2026, 11, 5, 6, 0))


def test_summary_body():
    assert morning_push_service.summary_body(1, 0) == "Hoy tienes 1 tarea. ¡Vamos!"
    assert (
        morning_push_service.summary_body(4, 2)
        == "Hoy tienes 4 tareas (2 de prioridad alta). ¡Vamos!"
    )


def _morning_db(subscriptions, pending=3, high=1):
    db = MagicMock()
    listing = MagicMock()
    listing.all.return_value = subscriptions
    counts = [MagicMock(), MagicMock()]
    counts[0].scalar.return_value = pending
    counts[1].scalar.return_value = high
    db.execute = AsyncMock(side_effect=[listing, *counts])
    return db


@pytest.mark.anyio
async def test_morning_summary_goes_out_at_7_local_time_once(vapid, monkeypatch):
    sent = AsyncMock(return_value=1)
    lock = AsyncMock(return_value=True)
    monkeypatch.setattr(morning_push_service.push_service, "send_to_user", sent)
    monkeypatch.setattr(morning_push_service.cache, "acquire_lock", lock)

    # 13:30 UTC is 7:30 in Mexico City
    db = _morning_db([("u1", "America/Mexico_City")])
    await morning_push_service.send_morning_pushes(db, datetime(2026, 11, 4, 13, 30))

    assert lock.await_args.args[0] == "push:morning:u1:2026-11-04"
    args, kwargs = sent.await_args
    assert args[1:] == ("u1", "☀️ Buenos días", "Hoy tienes 3 tareas (1 de prioridad alta). ¡Vamos!")
    assert kwargs["tag"] == "morning-summary"
    # No in-app version: shown even with Focusly on screen
    assert not kwargs.get("in_app")


@pytest.mark.anyio
async def test_no_morning_summary_outside_7_local(vapid, monkeypatch):
    sent = AsyncMock()
    monkeypatch.setattr(morning_push_service.push_service, "send_to_user", sent)
    monkeypatch.setattr(morning_push_service.cache, "acquire_lock", AsyncMock(return_value=True))

    # 7:30 UTC is 1:30 AM in Mexico City: the old summary's hour, never a push
    db = _morning_db([("u1", "America/Mexico_City")])
    await morning_push_service.send_morning_pushes(db, datetime(2026, 11, 4, 7, 30))
    sent.assert_not_called()


@pytest.mark.parametrize("lock_result", [False, None])
@pytest.mark.anyio
async def test_no_second_morning_summary_or_when_redis_is_down(vapid, monkeypatch, lock_result):
    sent = AsyncMock()
    monkeypatch.setattr(morning_push_service.push_service, "send_to_user", sent)
    monkeypatch.setattr(
        morning_push_service.cache, "acquire_lock", AsyncMock(return_value=lock_result)
    )
    db = _morning_db([("u1", "America/Mexico_City")])
    await morning_push_service.send_morning_pushes(db, datetime(2026, 11, 4, 13, 30))
    sent.assert_not_called()


@pytest.mark.anyio
async def test_no_morning_summary_on_an_empty_day(vapid, monkeypatch):
    sent = AsyncMock()
    monkeypatch.setattr(morning_push_service.push_service, "send_to_user", sent)
    monkeypatch.setattr(morning_push_service.cache, "acquire_lock", AsyncMock(return_value=True))
    db = _morning_db([("u1", "America/Mexico_City")], pending=0)
    await morning_push_service.send_morning_pushes(db, datetime(2026, 11, 4, 13, 30))
    sent.assert_not_called()


@pytest.mark.anyio
async def test_devices_without_a_time_zone_get_no_morning_summary(vapid, monkeypatch):
    sent = AsyncMock()
    monkeypatch.setattr(morning_push_service.push_service, "send_to_user", sent)
    db = _morning_db([("u1", None)])
    await morning_push_service.send_morning_pushes(db, datetime(2026, 11, 4, 13, 30))
    sent.assert_not_called()
