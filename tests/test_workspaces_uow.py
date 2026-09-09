import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models import Workspace, ProjectGroup, User
from app.modules.workspace.services.project_groups_service import ProjectGroupsService
from app.modules.workspace.services.workspaces_service import WorkspacesService
from app.modules.user.services.users_service import UsersService
from app.modules.workspace.infrastructure.persistence.repository import (
    WorkspacesRepository,
    ProjectGroupsRepository,
)
from app.modules.user.repository import UsersRepository


def make_mock_db():
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)

    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    db.begin = MagicMock(return_value=tx)

    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()
    db.merge = AsyncMock(side_effect=lambda x: x)
    return db, tx


@pytest.mark.anyio
async def test_project_groups_remove_rolls_back_if_group_delete_fails():
    """Test 1: If deleting the group fails after deleting its workspaces,
    the entire operation is rolled back atomically."""
    db, tx = make_mock_db()
    service = ProjectGroupsService(db=db)

    dummy_group = ProjectGroup(id="group-1", userId="user-1", name="Test Group")
    service.repository.get_by_id_and_user = AsyncMock(return_value=dummy_group)
    service.repository.delete_workspaces_by_group_id = AsyncMock()
    service.repository.delete = AsyncMock(side_effect=RuntimeError("DB disk full"))

    with pytest.raises(RuntimeError, match="DB disk full"):
        await service.remove("group-1", "user-1")

    service.repository.delete_workspaces_by_group_id.assert_called_once_with("group-1")
    service.repository.delete.assert_called_once_with(dummy_group)
    tx.__aexit__.assert_called_once()
    exc_type = tx.__aexit__.call_args[0][0]
    assert exc_type is RuntimeError


@pytest.mark.anyio
async def test_project_groups_remove_commits_atomically():
    """Test 2: When both workspaces and group are deleted, transaction commits cleanly."""
    db, tx = make_mock_db()
    service = ProjectGroupsService(db=db)

    dummy_group = ProjectGroup(id="group-1", userId="user-1", name="Test Group")
    service.repository.get_by_id_and_user = AsyncMock(return_value=dummy_group)
    service.repository.delete_workspaces_by_group_id = AsyncMock()
    service.repository.delete = AsyncMock()

    result = await service.remove("group-1", "user-1")

    assert result is True
    service.repository.delete_workspaces_by_group_id.assert_called_once_with("group-1")
    service.repository.delete.assert_called_once_with(dummy_group)
    tx.__aexit__.assert_called_once()
    exc_type = tx.__aexit__.call_args[0][0]
    assert exc_type is None


@pytest.mark.anyio
async def test_workspaces_service_update_with_task_id_atomic():
    """Test 3: WorkspacesService.update reassigns taskId and saves within transaction_scope."""
    db, tx = make_mock_db()
    service = WorkspacesService(db=db)

    dummy_ws = Workspace(id="ws-1", userId="user-1", title="Old Title")
    service.repository.get_by_id_and_user = AsyncMock(return_value=dummy_ws)
    service.repository.release_taskId_for_other_workspaces = AsyncMock()
    service.repository.save = AsyncMock(return_value=dummy_ws)

    updated = await service.update(
        "ws-1", {"taskId": "task-123", "title": "New Title"}, "user-1"
    )

    assert updated.title == "New Title"
    service.repository.release_taskId_for_other_workspaces.assert_called_once()
    service.repository.save.assert_called_once()
    tx.__aexit__.assert_called_once()
    exc_type = tx.__aexit__.call_args[0][0]
    assert exc_type is None


@pytest.mark.anyio
async def test_workspaces_service_update_rolls_back_on_save_failure():
    """Test 4: If save fails during update, release_taskId is rolled back."""
    db, tx = make_mock_db()
    service = WorkspacesService(db=db)

    dummy_ws = Workspace(id="ws-1", userId="user-1", title="Old Title")
    service.repository.get_by_id_and_user = AsyncMock(return_value=dummy_ws)
    service.repository.release_taskId_for_other_workspaces = AsyncMock()
    service.repository.save = AsyncMock(side_effect=RuntimeError("Constraint violation"))

    with pytest.raises(RuntimeError, match="Constraint violation"):
        await service.update("ws-1", {"taskId": "task-123"}, "user-1")

    tx.__aexit__.assert_called_once()
    exc_type = tx.__aexit__.call_args[0][0]
    assert exc_type is RuntimeError


@pytest.mark.anyio
async def test_users_service_update_commits_atomically():
    """Test 5: UsersService.update commits atomically within transaction_scope."""
    db, tx = make_mock_db()
    service = UsersService(db=db)

    dummy_user = User(id="user-1", email="test@focusly.app", name="Old Name")
    service.repository.get_by_id = AsyncMock(return_value=dummy_user)
    service.repository.save = AsyncMock(return_value=dummy_user)

    updated = await service.update("user-1", {"name": "New Name"})

    assert updated.name == "New Name"
    service.repository.save.assert_called_once()
    tx.__aexit__.assert_called_once()
    assert tx.__aexit__.call_args[0][0] is None


@pytest.mark.anyio
async def test_workspaces_repo_defaults_to_flush():
    """Test 6: WorkspacesRepository methods default to commit=False and call flush(), not commit()."""
    db, _ = make_mock_db()
    repo = WorkspacesRepository(db=db)
    ws = Workspace(id="ws-1", userId="user-1", title="Test")

    # create defaults to commit=False
    await repo.create(ws)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # save defaults to commit=False
    db.flush.reset_mock()
    db.commit.reset_mock()
    await repo.save(ws)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # delete defaults to commit=False
    db.flush.reset_mock()
    db.commit.reset_mock()
    await repo.delete(ws)
    db.flush.assert_called_once()
    db.commit.assert_not_called()


@pytest.mark.anyio
async def test_users_repo_defaults_to_flush():
    """Test 7: UsersRepository methods default to commit=False and call flush(), not commit()."""
    db, _ = make_mock_db()
    repo = UsersRepository(db=db)
    user = User(id="user-1", email="test@focusly.app")

    # create defaults to commit=False
    await repo.create(user)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # save defaults to commit=False
    db.flush.reset_mock()
    db.commit.reset_mock()
    await repo.save(user)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # delete defaults to commit=False
    db.flush.reset_mock()
    db.commit.reset_mock()
    await repo.delete(user)
    db.flush.assert_called_once()
    db.commit.assert_not_called()
