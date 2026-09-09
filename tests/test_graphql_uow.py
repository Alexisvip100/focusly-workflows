import pytest
from unittest.mock import AsyncMock, MagicMock
import strawberry

from app.graphql.extensions import TransactionalMutationExtension
from app.models import Tag, FocusSession, Notification
from app.modules.task.infrastructure.persistence.repository import (
    TagsRepository,
    FocusSessionsRepository,
)
from app.modules.notification.repository import NotificationsRepository


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


@strawberry.type
class SampleQuery:
    @strawberry.field
    def ping(self) -> str:
        return "pong"


@strawberry.type
class SampleMutation:
    @strawberry.mutation
    async def success_mutation(self, info) -> str:
        db = info.context["db"]
        db.add("item")
        await db.flush()
        return "success"

    @strawberry.mutation
    async def failing_mutation(self, info) -> str:
        raise ValueError("Mutation intentional failure")


test_schema = strawberry.Schema(
    query=SampleQuery,
    mutation=SampleMutation,
    extensions=[TransactionalMutationExtension],
)


@pytest.mark.anyio
async def test_graphql_mutation_extension_commits_on_success():
    """Test 1: Successful GraphQL mutation executes inside transaction and commits."""
    db, tx = make_mock_db()

    result = await test_schema.execute(
        "mutation { successMutation }", context_value={"db": db}
    )

    assert result.errors is None
    assert result.data == {"successMutation": "success"}
    db.begin.assert_called_once()
    tx.__aenter__.assert_called_once()
    tx.__aexit__.assert_called_once()
    assert tx.__aexit__.call_args[0][0] is None


@pytest.mark.anyio
async def test_graphql_mutation_extension_rolls_back_on_error():
    """Test 2: Failing GraphQL mutation triggers rollback via transaction_scope."""
    db, tx = make_mock_db()

    result = await test_schema.execute(
        "mutation { failingMutation }", context_value={"db": db}
    )

    assert result.errors is not None
    db.begin.assert_called_once()
    tx.__aenter__.assert_called_once()
    tx.__aexit__.assert_called_once()
    # Rolled back due to error in transaction_scope
    exc_type = tx.__aexit__.call_args[0][0]
    assert exc_type is not None


@pytest.mark.anyio
async def test_graphql_query_does_not_open_transaction():
    """Test 3: GraphQL queries remain read-only and never open DB transactions."""
    db, tx = make_mock_db()

    result = await test_schema.execute("{ ping }", context_value={"db": db})

    assert result.errors is None
    assert result.data == {"ping": "pong"}
    db.begin.assert_not_called()
    tx.__aenter__.assert_not_called()


@pytest.mark.anyio
async def test_tags_and_focus_sessions_repositories_default_to_flush():
    """Test 4: TagsRepository & FocusSessionsRepository default to commit=False and call flush()."""
    db, _ = make_mock_db()
    tags_repo = TagsRepository(db=db)
    focus_repo = FocusSessionsRepository(db=db)

    tag = Tag(id="t1", name="Work")
    await tags_repo.create(tag)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    db.flush.reset_mock()
    db.commit.reset_mock()
    session = FocusSession(id="fs1", userId="u1")
    await focus_repo.create(session)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    db.flush.reset_mock()
    await focus_repo.save(session)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    db.flush.reset_mock()
    await focus_repo.delete(session)
    db.flush.assert_called_once()
    db.commit.assert_not_called()


@pytest.mark.anyio
async def test_notifications_repository_defaults_to_flush():
    """Test 5: NotificationsRepository methods default to commit=False and flush()."""
    db, _ = make_mock_db()
    notif_repo = NotificationsRepository(db=db)
    notif = Notification(id="n1", userId="u1", title="Alert")

    # create
    await notif_repo.create(notif)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # save
    db.flush.reset_mock()
    await notif_repo.save(notif)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # delete
    db.flush.reset_mock()
    await notif_repo.delete(notif)
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # mark_all_read
    db.flush.reset_mock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=3))
    await notif_repo.mark_all_read("u1")
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # delete_by_id_and_user
    db.flush.reset_mock()
    await notif_repo.delete_by_id_and_user("n1", "u1")
    db.flush.assert_called_once()
    db.commit.assert_not_called()

    # delete_all_by_user
    db.flush.reset_mock()
    await notif_repo.delete_all_by_user("u1")
    db.flush.assert_called_once()
    db.commit.assert_not_called()
