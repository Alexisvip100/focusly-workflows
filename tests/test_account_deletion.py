import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import User
from app.modules.user.services.account_deletion_service import (
    AccountDeletionService,
    USER_OWNED_MODELS,
)


def make_db(ids):
    """Mock AsyncSession whose id lookups return `ids` and that records deletes."""
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    db.begin = MagicMock(return_value=tx)

    result = MagicMock()
    result.scalars.return_value.all.return_value = ids
    db.execute = AsyncMock(return_value=result)
    return db


def executed_sql(db):
    return [str(call.args[0]) for call in db.execute.call_args_list]


@pytest.mark.anyio
async def test_delete_account_removes_every_user_table_and_cache():
    db = make_db(["id-1"])
    user = User(id="user-1", email="u1@example.com")
    service = AccountDeletionService(db)

    with patch.object(service, "_stop_calendar_sync", AsyncMock()), patch.object(
        service, "_delete_avatars", MagicMock()
    ) as delete_avatars, patch(
        "app.modules.user.services.account_deletion_service.UsersRepository"
    ) as users_repo_cls, patch(
        "app.modules.user.services.account_deletion_service.cache"
    ) as cache:
        users_repo_cls.return_value.delete = AsyncMock()
        cache.delete = AsyncMock()

        await service.delete_account(user)

    deleted_tables = {
        sql.split('"')[1] for sql in executed_sql(db) if sql.startswith("DELETE FROM")
    }
    assert deleted_tables == {m.__tablename__ for m in USER_OWNED_MODELS} | {"Message"}
    users_repo_cls.return_value.delete.assert_awaited_once_with(user)
    delete_avatars.assert_called_once_with("user-1")

    deleted_keys = {c.args[0] for c in cache.delete.call_args_list}
    assert {"task:id:id-1", "workspace:id:id-1", "conversation:messages:id-1"} <= deleted_keys
    assert "tasks:active:user:user-1" in deleted_keys


@pytest.mark.anyio
async def test_delete_account_survives_external_cleanup_failures():
    db = make_db([])
    user = User(id="user-1", email="u1@example.com", googleRefreshToken="refresh-token")
    service = AccountDeletionService(db)

    with patch(
        "app.modules.google_calendar.services.google_calendar_service.GoogleCalendarService.stop_watching_calendar",
        AsyncMock(side_effect=RuntimeError("google down")),
    ), patch(
        "app.modules.user.services.account_deletion_service.httpx.AsyncClient.post",
        AsyncMock(side_effect=RuntimeError("network down")),
    ), patch(
        "app.modules.storage.services.storage_service.delete_user_avatar_objects",
        MagicMock(side_effect=RuntimeError("storage down")),
    ), patch(
        "app.modules.user.services.account_deletion_service.UsersRepository"
    ) as users_repo_cls, patch(
        "app.modules.user.services.account_deletion_service.cache"
    ) as cache:
        users_repo_cls.return_value.delete = AsyncMock()
        cache.delete = AsyncMock()

        await service.delete_account(user)

    users_repo_cls.return_value.delete.assert_awaited_once_with(user)
