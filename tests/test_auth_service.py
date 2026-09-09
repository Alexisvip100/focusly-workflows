import pytest
from unittest.mock import AsyncMock, patch
from app.modules.auth.services.auth_service import AuthService
from app.config import settings


@pytest.mark.anyio
async def test_send_magic_link_uses_frontend_url_and_logs_dev(monkeypatch, caplog):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.focusly.com")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "IS_PRODUCTION", False)

    auth_service = AuthService(db=None)

    with caplog.at_level("WARNING"):
        await auth_service.send_magic_link("test@example.com", "token-xyz-123")

    assert "https://app.focusly.com/login?token=token-xyz-123" in caplog.text


@pytest.mark.anyio
async def test_send_magic_link_does_not_leak_token_in_production(monkeypatch, caplog):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.focusly.com")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "IS_PRODUCTION", True)

    auth_service = AuthService(db=None)

    with caplog.at_level("ERROR"):
        await auth_service.send_magic_link("victim@example.com", "secret-token-do-not-leak")

    assert "secret-token-do-not-leak" not in caplog.text
    assert "RESEND_API_KEY is not configured in production" in caplog.text
