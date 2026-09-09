import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.user.routes import router, get_users_service
from app.routes.common import get_current_user_id


def make_user(**kwargs):
    defaults = {
        "id": "user-1",
        "email": "user1@example.com",
        "name": "User One",
        "picture": "avatar.jpg",
        "role": "user",
        "bio": "Bio one",
        "authProvider": "email",
        "subscriptionStatus": "free",
        "settings": {"theme": "dark"},
        "fcmToken": "token-123",
        "createdAt": datetime(2026, 1, 1, 12, 0, 0),
        "updatedAt": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.fixture
def mock_users_service():
    service = MagicMock()
    service.findOne = AsyncMock()
    service.update = AsyncMock()
    service.find = AsyncMock()
    service.create = AsyncMock()
    return service


@pytest.fixture
def app_and_client(mock_users_service, monkeypatch):
    monkeypatch.setattr("app.modules.user.routes.delete_avatar_object", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_users_service] = lambda: mock_users_service

    # Default authentication as user-1
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    client = TestClient(app)
    return app, client, mock_users_service


class TestUserAccessControl:
    # Scenario 1: un usuario normal intentando hacer PATCH sobre el id de otro usuario -> 403
    def test_normal_user_cannot_patch_another_user(self, app_and_client):
        app, client, mock_service = app_and_client
        current_user = make_user(id="user-1", role="user")
        other_user = make_user(id="user-2", role="user")

        mock_service.findOne.side_effect = lambda uid: (
            current_user if uid == "user-1" else other_user
        )

        response = client.patch("/users/user-2", json={"name": "Hacked Name"})

        assert response.status_code == 403
        assert response.json()["detail"] == "You do not have permission to modify this user account"
        mock_service.update.assert_not_called()

    # Scenario 2: un usuario normal mandando role/subscriptionStatus con el MISMO valor que ya tiene -> debe pasar sin error (200)
    def test_normal_user_sending_same_role_and_subscription_passes(self, app_and_client):
        app, client, mock_service = app_and_client
        user = make_user(id="user-1", role="user", subscriptionStatus="free", name="Old Name")

        mock_service.findOne.return_value = user

        updated_user = make_user(id="user-1", role="user", subscriptionStatus="free", name="New Name")
        mock_service.update.return_value = updated_user

        response = client.patch(
            "/users/user-1",
            json={
                "name": "New Name",
                "role": "user",
                "subscriptionStatus": "free",
            },
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"
        # Confirm that redundant role and subscriptionStatus are stripped from update payload
        mock_service.update.assert_called_once_with(
            "user-1",
            {"name": "New Name"},
        )

    # Scenario 3: un usuario normal intentando CAMBIAR su role o subscriptionStatus -> 403
    def test_normal_user_changing_role_is_forbidden(self, app_and_client):
        app, client, mock_service = app_and_client
        user = make_user(id="user-1", role="user", subscriptionStatus="free")
        mock_service.findOne.return_value = user

        response = client.patch("/users/user-1", json={"role": "admin"})

        assert response.status_code == 403
        assert "Only administrators can modify user roles" in response.json()["detail"]
        mock_service.update.assert_not_called()

    def test_normal_user_changing_subscription_status_is_forbidden(self, app_and_client):
        app, client, mock_service = app_and_client
        user = make_user(id="user-1", role="user", subscriptionStatus="free")
        mock_service.findOne.return_value = user

        response = client.patch("/users/user-1", json={"subscriptionStatus": "pro"})

        assert response.status_code == 403
        assert "Only administrators can modify subscription status" in response.json()["detail"]
        mock_service.update.assert_not_called()

    # Additional verification: Admin can change another user's role and subscriptionStatus
    def test_admin_can_patch_another_user_role_and_subscription(self, app_and_client):
        app, client, mock_service = app_and_client
        admin_user = make_user(id="admin-1", role="admin")
        target_user = make_user(id="user-2", role="user", subscriptionStatus="free")

        app.dependency_overrides[get_current_user_id] = lambda: "admin-1"

        mock_service.findOne.side_effect = lambda uid: (
            admin_user if uid == "admin-1" else target_user
        )

        updated_target = make_user(id="user-2", role="admin", subscriptionStatus="pro")
        mock_service.update.return_value = updated_target

        response = client.patch(
            "/users/user-2",
            json={"role": "admin", "subscriptionStatus": "pro"},
        )

        assert response.status_code == 200
        mock_service.update.assert_called_once_with(
            "user-2",
            {"role": "admin", "subscriptionStatus": "pro"},
        )

    # Verification of GET /users access control (admin only)
    def test_normal_user_cannot_list_all_users(self, app_and_client):
        app, client, mock_service = app_and_client
        user = make_user(id="user-1", role="user")
        mock_service.findOne.return_value = user

        response = client.get("/users")

        assert response.status_code == 403
        assert response.json()["detail"] == "Admin privileges required"

    def test_admin_can_list_all_users(self, app_and_client):
        app, client, mock_service = app_and_client
        admin = make_user(id="admin-1", role="admin")
        app.dependency_overrides[get_current_user_id] = lambda: "admin-1"
        mock_service.findOne.return_value = admin
        mock_service.find.return_value = [admin, make_user(id="user-2")]

        response = client.get("/users")

        assert response.status_code == 200
        assert len(response.json()) == 2

    # Verification of GET /users/{id}
    def test_normal_user_cannot_view_other_user_private_profile(self, app_and_client):
        app, client, mock_service = app_and_client
        user = make_user(id="user-1", role="user")
        mock_service.findOne.return_value = user

        response = client.get("/users/user-2")

        assert response.status_code == 403
        assert "You do not have permission" in response.json()["detail"]

    def test_user_can_view_own_profile(self, app_and_client):
        app, client, mock_service = app_and_client
        user = make_user(id="user-1", role="user")
        mock_service.findOne.return_value = user

        response = client.get("/users/user-1")

        assert response.status_code == 200
        assert response.json()["id"] == "user-1"
        assert response.json()["email"] == "user1@example.com"

    # Verification of public profile endpoint
    def test_public_profile_does_not_leak_sensitive_fields(self, app_and_client):
        app, client, mock_service = app_and_client
        target_user = make_user(id="user-2", name="Target", bio="Public bio", email="secret@test.com")
        mock_service.findOne.return_value = target_user

        response = client.get("/users/user-2/public-profile")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "user-2"
        assert data["name"] == "Target"
        assert data["bio"] == "Public bio"
        assert "email" not in data
        assert "settings" not in data
        assert "fcmToken" not in data
        assert "googleRefreshToken" not in data
