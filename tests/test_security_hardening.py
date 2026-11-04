"""The fixes from the security audit: request limits on sign-in, honest
magic-link errors, no internal error text in responses, verified Calendar
webhooks, and no API docs / GraphiQL / introspection in production."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.database import get_db
from app.modules.auth import routes as auth_routes
from app.modules.google_calendar import routes as gcal_routes
from app.redis import ResilientRedisCache
from app.routes import rate_limit


# ─── Rate limiting ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_requests_over_the_limit_are_refused(monkeypatch):
    monkeypatch.setattr(rate_limit.cache, "count_in_window", AsyncMock(return_value=4))
    with pytest.raises(HTTPException) as refused:
        await rate_limit.enforce("magic-link-email", "a@b.com", 3, 900)
    assert refused.value.status_code == 429
    assert refused.value.headers == {"Retry-After": "900"}


@pytest.mark.anyio
async def test_requests_within_the_limit_pass(monkeypatch):
    monkeypatch.setattr(rate_limit.cache, "count_in_window", AsyncMock(return_value=3))
    await rate_limit.enforce("magic-link-email", "a@b.com", 3, 900)


@pytest.mark.anyio
async def test_a_redis_outage_never_locks_people_out(monkeypatch):
    monkeypatch.setattr(rate_limit.cache, "count_in_window", AsyncMock(return_value=None))
    await rate_limit.enforce("google-login", "1.2.3.4", 1, 60)


@pytest.mark.anyio
async def test_limit_keys_hide_the_email_and_ignore_case(monkeypatch):
    counter = AsyncMock(return_value=1)
    monkeypatch.setattr(rate_limit.cache, "count_in_window", counter)
    await rate_limit.enforce("magic-link-email", "Ana@Example.com", 3, 900)
    await rate_limit.enforce("magic-link-email", "ana@example.com ", 3, 900)
    first, second = (call.args[0] for call in counter.await_args_list)
    assert first == second
    assert "ana" not in first and first.startswith("ratelimit:magic-link-email:")


def test_client_ip_is_the_first_forwarded_address():
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, client=SimpleNamespace(host="10.0.0.1")
    )
    assert rate_limit.client_ip(request) == "203.0.113.7"
    direct = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    assert rate_limit.client_ip(direct) == "127.0.0.1"


@pytest.mark.anyio
async def test_window_counter_sets_the_expiry_on_the_first_hit_only():
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[True, 1])
    redis = ResilientRedisCache("redis://unused")
    redis.client = MagicMock()
    redis.client.pipeline.return_value = pipe
    redis._ensure_connected = AsyncMock(return_value=True)

    assert await redis.count_in_window("k", 60) == 1
    pipe.set.assert_called_once_with("k", 0, ex=60, nx=True)
    pipe.incr.assert_called_once_with("k")


@pytest.mark.anyio
async def test_window_counter_reports_redis_down():
    redis = ResilientRedisCache("redis://unused")
    redis._ensure_connected = AsyncMock(return_value=False)
    assert await redis.count_in_window("k", 60) is None


# ─── Sign-in routes ─────────────────────────────────────────────────────────


@pytest.fixture
def auth_app(monkeypatch):
    service = MagicMock()
    service.generate_magic_link_token.return_value = "tok"
    service.send_magic_link = AsyncMock(return_value=True)
    service.validate_google_token = AsyncMock()
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.dependency_overrides[auth_routes.get_auth_service] = lambda: service
    monkeypatch.setattr(rate_limit.cache, "count_in_window", AsyncMock(return_value=1))
    return TestClient(app), service


def test_magic_link_is_sent(auth_app):
    client, service = auth_app
    response = client.post("/auth/magic-link", json={"email": "ana@example.com"})
    assert response.status_code == 200
    service.send_magic_link.assert_awaited_once_with("ana@example.com", "tok")


def test_magic_link_that_could_not_be_sent_says_so(auth_app):
    client, service = auth_app
    service.send_magic_link.return_value = False
    response = client.post("/auth/magic-link", json={"email": "ana@example.com"})
    assert response.status_code == 503
    assert "No pudimos enviar el correo" in response.json()["detail"]


def test_magic_link_needs_a_real_email(auth_app):
    client, service = auth_app
    assert client.post("/auth/magic-link", json={"email": "not-an-email"}).status_code == 422
    service.send_magic_link.assert_not_called()


def test_magic_link_requests_are_limited(auth_app, monkeypatch):
    client, service = auth_app
    monkeypatch.setattr(rate_limit.cache, "count_in_window", AsyncMock(return_value=99))
    response = client.post("/auth/magic-link", json={"email": "ana@example.com"})
    assert response.status_code == 429
    assert response.headers["retry-after"]
    service.send_magic_link.assert_not_called()


def test_magic_link_verification_is_limited(auth_app, monkeypatch):
    client, _ = auth_app
    monkeypatch.setattr(rate_limit.cache, "count_in_window", AsyncMock(return_value=99))
    assert client.post("/auth/magic-link/verify", json={"token": "x"}).status_code == 429


def test_google_sign_in_hides_the_internal_reason(auth_app):
    client, service = auth_app
    service.validate_google_token.side_effect = ValueError(
        "Invalid Google OAuth Token: invalid_grant client_secret=..."
    )
    response = client.post("/auth/google", json={"code": "c"})
    assert response.status_code == 401
    assert response.json()["detail"] == "No pudimos iniciar sesión con Google."


def test_google_sign_in_is_limited(auth_app, monkeypatch):
    client, service = auth_app
    monkeypatch.setattr(rate_limit.cache, "count_in_window", AsyncMock(return_value=99))
    assert client.post("/auth/google", json={"code": "c"}).status_code == 429
    service.validate_google_token.assert_not_called()


# ─── Magic link sender ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sender_reports_a_refused_email(monkeypatch):
    from app.modules.auth.services import auth_service as module

    monkeypatch.setattr(module.settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(module.settings, "EMAIL_FROM", "Focusly <hola@focusly.app>")
    sent = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, headers=None, json=None):
            sent.update(json)
            return SimpleNamespace(status_code=403, text="domain not verified")

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    service = module.AuthService(MagicMock())
    assert await service.send_magic_link("ana@example.com", "tok") is False
    assert sent["from"] == "Focusly <hola@focusly.app>"


@pytest.mark.anyio
async def test_sender_without_resend_fails_in_production_only(monkeypatch):
    from app.modules.auth.services import auth_service as module

    monkeypatch.setattr(module.settings, "RESEND_API_KEY", "")
    service = module.AuthService(MagicMock())
    monkeypatch.setattr(module.settings, "IS_PRODUCTION", True)
    assert await service.send_magic_link("ana@example.com", "tok") is False
    monkeypatch.setattr(module.settings, "IS_PRODUCTION", False)
    assert await service.send_magic_link("ana@example.com", "tok") is True


# ─── Calendar webhook ───────────────────────────────────────────────────────


@pytest.fixture
def webhook(monkeypatch):
    app = FastAPI()
    app.include_router(gcal_routes.router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    user = SimpleNamespace(id="u1", googleChannelId="chan-123")
    repo = MagicMock()
    repo.get_by_id = AsyncMock(side_effect=lambda uid: user if uid == "u1" else None)
    monkeypatch.setattr(gcal_routes, "UsersRepository", lambda db: repo)
    sync = AsyncMock()
    monkeypatch.setattr(gcal_routes, "start_background_sync", sync)
    return TestClient(app), sync


def _notify(client, channel, token):
    return client.post(
        "/google-calendar/webhook",
        headers={
            "x-goog-resource-state": "exists",
            "x-goog-channel-id": channel,
            "x-goog-channel-token": token,
        },
    )


def test_webhook_syncs_for_the_registered_channel(webhook):
    client, sync = webhook
    assert _notify(client, "chan-123", "u1").json() == {"status": "sync_triggered"}
    sync.assert_awaited_once()


def test_webhook_ignores_a_forged_notification(webhook):
    client, sync = webhook
    # Knowing the user id isn't enough without the channel's random id
    assert _notify(client, "guessed", "u1").json() == {"status": "ignored"}
    assert _notify(client, "chan-123", "someone-else").json() == {"status": "ignored"}
    sync.assert_not_called()


# ─── Production surface ─────────────────────────────────────────────────────


PROBE = r"""
import json
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app.other_asgi_app if hasattr(app, "other_asgi_app") else app)
introspect = c.post("/graphql", json={"query": "{ __schema { types { name } } }"})
typename = c.post("/graphql", json={"query": "{ __typename }"})
print(json.dumps({
    "docs": c.get("/docs").status_code,
    "redoc": c.get("/redoc").status_code,
    "openapi": c.get("/openapi.json").status_code,
    "graphiql": c.get("/graphql", headers={"accept": "text/html"}).status_code,
    "introspection_blocked": bool(introspect.json().get("errors")),
    "typename": typename.json().get("data"),
}))
"""


def _probe(env_name: str) -> dict:
    env = {
        **os.environ,
        "ENV": env_name,
        "JWT_SECRET": "test-secret-for-the-probe",
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "RUN_NOTIFIER_LOOPS": "0",
    }
    out = subprocess.run(  # noqa: S603 (this interpreter, a fixed script)
        [sys.executable, "-c", PROBE],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_production_hides_docs_graphiql_and_the_schema():
    result = _probe("production")
    assert result["docs"] == 404
    assert result["redoc"] == 404
    assert result["openapi"] == 404
    assert result["graphiql"] != 200
    assert result["introspection_blocked"] is True
    assert result["typename"] == {"__typename": "Query"}


def test_development_keeps_them():
    result = _probe("development")
    assert result["docs"] == 200
    assert result["openapi"] == 200
    assert result["graphiql"] == 200
    assert result["introspection_blocked"] is False
