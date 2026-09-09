import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.task.routes.time_blocks import (
    router,
    get_time_blocks_service,
    get_users_service,
    get_tasks_repository,
)
from app.routes.common import get_current_user_id


def make_user(**kwargs):
    defaults = {
        "id": "user-1",
        "email": "user1@example.com",
        "name": "User One",
        "picture": None,
        "role": "user",
        "subscriptionStatus": "free",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_task(**kwargs):
    defaults = {
        "id": "task-1",
        "userId": "user-1",
        "title": "Task One",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_time_block(**kwargs):
    defaults = {
        "id": "tb-1",
        "userId": "user-1",
        "taskId": "task-1",
        "startTime": "2026-09-08T10:00:00Z",
        "endTime": "2026-09-08T11:00:00Z",
        "blockType": "Focus_Block",
        "externalEventId": None,
        "source": "App",
        "title": "Focus Session",
        "meetingUrl": None,
        "attendees": [],
        "createdAt": datetime(2026, 9, 8, 10, 0, 0).isoformat(),
        "updatedAt": datetime(2026, 9, 8, 10, 0, 0).isoformat(),
    }
    defaults.update(kwargs)
    return defaults


@pytest.fixture
def mock_tb_service():
    service = MagicMock()
    service.create = AsyncMock(return_value="new-tb-id")
    service.find_all = AsyncMock(return_value=[])
    service.find_one = AsyncMock()
    service.find_all_by_user = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_users_service():
    service = MagicMock()
    service.findOne = AsyncMock()
    return service


@pytest.fixture
def mock_tasks_repo():
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    return repo


@pytest.fixture
def app_and_client(mock_tb_service, mock_users_service, mock_tasks_repo):
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_time_blocks_service] = lambda: mock_tb_service
    app.dependency_overrides[get_users_service] = lambda: mock_users_service
    app.dependency_overrides[get_tasks_repository] = lambda: mock_tasks_repo
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    client = TestClient(app)
    return app, client, mock_tb_service, mock_users_service, mock_tasks_repo


class TestTimeBlocksAccessControl:
    # 1. Usuario normal crea un bloque -> userId queda forzado a su propio id sin importar lo que mandó en el body.
    def test_create_forces_authenticated_user_id(self, app_and_client):
        _, client, mock_tb, _, _ = app_and_client

        payload = {
            "userId": "attacker-targeted-user",
            "startTime": "2026-09-08T10:00:00Z",
            "endTime": "2026-09-08T11:00:00Z",
            "blockType": "Focus_Block",
            "source": "App",
            "title": "Deep Work",
        }

        response = client.post("/time-blocks", json=payload)

        assert response.status_code == 200
        assert response.json() == "new-tb-id"
        mock_tb.create.assert_called_once()
        passed_data = mock_tb.create.call_args[0][0]
        assert passed_data["userId"] == "user-1"

    # 2. Usuario normal intenta GET /time-blocks/user/{otro_id} -> 403.
    def test_normal_user_cannot_view_another_user_time_blocks(self, app_and_client):
        _, client, mock_tb, mock_users, _ = app_and_client
        current_user = make_user(id="user-1", role="user")
        mock_users.findOne.return_value = current_user

        response = client.get("/time-blocks/user/user-2")

        assert response.status_code == 403
        assert "You do not have permission" in response.json()["detail"]
        mock_tb.find_all_by_user.assert_not_called()

    # 3. Admin puede ver time blocks de cualquier usuario.
    def test_admin_can_view_any_user_time_blocks(self, app_and_client):
        app, client, mock_tb, mock_users, _ = app_and_client
        admin_user = make_user(id="admin-1", role="admin")
        app.dependency_overrides[get_current_user_id] = lambda: "admin-1"
        mock_users.findOne.return_value = admin_user
        mock_tb.find_all_by_user.return_value = [make_time_block(userId="user-2")]

        response = client.get("/time-blocks/user/user-2")

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["userId"] == "user-2"
        mock_tb.find_all_by_user.assert_called_once_with("user-2")

    # 4. Usuario normal intenta GET /time-blocks/{id} de un bloque ajeno -> 403.
    def test_normal_user_cannot_view_foreign_time_block(self, app_and_client):
        _, client, mock_tb, mock_users, _ = app_and_client
        current_user = make_user(id="user-1", role="user")
        mock_users.findOne.return_value = current_user
        mock_tb.find_one.return_value = make_time_block(id="tb-2", userId="user-2")

        response = client.get("/time-blocks/tb-2")

        assert response.status_code == 403
        assert "You do not have permission" in response.json()["detail"]

    # 5. GET /time-blocks/{id} de un bloque inexistente -> 404.
    def test_view_nonexistent_time_block_returns_404(self, app_and_client):
        _, client, mock_tb, _, _ = app_and_client
        mock_tb.find_one.side_effect = ValueError("Time block with ID nonexistent not found")

        response = client.get("/time-blocks/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    # 6. Usuario normal intenta crear un time block con taskId de una tarea que pertenece a OTRO usuario -> 403.
    def test_create_with_foreign_task_id_returns_403(self, app_and_client):
        _, client, mock_tb, _, mock_tasks = app_and_client
        foreign_task = make_task(id="task-foreign", userId="user-2")
        mock_tasks.get_by_id.return_value = foreign_task

        payload = {
            "taskId": "task-foreign",
            "startTime": "2026-09-08T10:00:00Z",
            "endTime": "2026-09-08T11:00:00Z",
            "blockType": "Focus_Block",
            "source": "App",
            "title": "Task linking attack",
        }

        response = client.post("/time-blocks", json=payload)

        assert response.status_code == 403
        assert "You do not have permission to link a task belonging to another user" in response.json()["detail"]
        mock_tb.create.assert_not_called()

    # 6b. Usuario normal intenta crear un time block con taskId inexistente -> 404.
    def test_create_with_nonexistent_task_id_returns_404(self, app_and_client):
        _, client, mock_tb, _, mock_tasks = app_and_client
        mock_tasks.get_by_id.return_value = None

        payload = {
            "taskId": "task-ghost",
            "startTime": "2026-09-08T10:00:00Z",
            "endTime": "2026-09-08T11:00:00Z",
            "blockType": "Focus_Block",
            "source": "App",
            "title": "Ghost Task",
        }

        response = client.post("/time-blocks", json=payload)

        assert response.status_code == 404
        assert "Task with ID task-ghost not found" in response.json()["detail"]
        mock_tb.create.assert_not_called()

    # Extra: Usuario normal crea time block con su propio taskId -> 200.
    def test_create_with_own_task_id_succeeds(self, app_and_client):
        _, client, mock_tb, _, mock_tasks = app_and_client
        own_task = make_task(id="task-own", userId="user-1")
        mock_tasks.get_by_id.return_value = own_task

        payload = {
            "taskId": "task-own",
            "startTime": "2026-09-08T10:00:00Z",
            "endTime": "2026-09-08T11:00:00Z",
            "blockType": "Focus_Block",
            "source": "App",
            "title": "Legit task focus",
        }

        response = client.post("/time-blocks", json=payload)

        assert response.status_code == 200
        mock_tb.create.assert_called_once()
        passed_data = mock_tb.create.call_args[0][0]
        assert passed_data["userId"] == "user-1"
        assert passed_data["taskId"] == "task-own"

    # Extra: GET /time-blocks raíz restringe a usuario normal a sus propios bloques
    def test_root_get_scopes_to_own_blocks_for_normal_user(self, app_and_client):
        _, client, mock_tb, mock_users, _ = app_and_client
        normal_user = make_user(id="user-1", role="user")
        mock_users.findOne.return_value = normal_user
        mock_tb.find_all_by_user.return_value = [make_time_block(userId="user-1")]

        response = client.get("/time-blocks")

        assert response.status_code == 200
        mock_tb.find_all_by_user.assert_called_once_with("user-1")
        mock_tb.find_all.assert_not_called()

    # Extra: GET /time-blocks raíz permite a admin ver todo
    def test_root_get_allows_admin_to_view_all(self, app_and_client):
        app, client, mock_tb, mock_users, _ = app_and_client
        admin_user = make_user(id="admin-1", role="admin")
        app.dependency_overrides[get_current_user_id] = lambda: "admin-1"
        mock_users.findOne.return_value = admin_user
        mock_tb.find_all.return_value = [
            make_time_block(userId="user-1"),
            make_time_block(userId="user-2"),
        ]

        response = client.get("/time-blocks")

        assert response.status_code == 200
        assert len(response.json()) == 2
        mock_tb.find_all.assert_called_once()
        mock_tb.find_all_by_user.assert_not_called()
