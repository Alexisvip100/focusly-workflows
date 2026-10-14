"""Upcoming-task reminders: the worker's sweep, what it skips, and what makes
a task remind again."""

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Task
from app.modules.notification.services import smart_notifier_service as smart
from app.modules.notification.services import sweep_lock
from app.modules.notification.services import task_notifier_service as notifier
from app.redis import ResilientRedisCache
from app.modules.task.infrastructure.persistence.repository import (
    INACTIVE_STATUSES,
    TasksRepository,
)
from app.modules.task.services.tasks.tasks_service import TasksService


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _task(**over) -> Task:
    start = _now() + timedelta(hours=2)
    fields = dict(
        id="t1",
        userId="u1",
        title="Escribir informe",
        status="Scheduled",
        estimated_start_date=start,
        estimated_end_date=start + timedelta(hours=1),
        deadline=start + timedelta(days=1),
        notified=True,
        lastMinuteNotified=True,
    )
    fields.update(over)
    return Task(**fields)


# ── Rescheduling by hand ─────────────────────────────────────────────────────


def _service(task: Task) -> TasksService:
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    db.begin = MagicMock(return_value=tx)

    service = TasksService(db=db)
    service.repository = MagicMock()
    service.repository.get_by_id = AsyncMock(return_value=task)
    service.repository.save = AsyncMock()
    service.sync_service = MagicMock()
    service.sync_service.sync_update_to_google = AsyncMock()
    service.sync_service.trigger_scheduler_pipeline = AsyncMock()
    service.sync_service.emit_schedule_updated = AsyncMock()
    return service


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["estimated_start_date", "deadline"])
async def test_a_new_start_time_reminds_again(field):
    task = _task()
    new_value = (getattr(task, field) + timedelta(hours=3)).isoformat()

    await _service(task).update("t1", {field: new_value}, skip_scheduling=True)

    assert task.notified is False
    assert task.lastMinuteNotified is False


@pytest.mark.anyio
async def test_same_time_keeps_the_reminders_already_sent():
    task = _task()

    await _service(task).update(
        "t1",
        {"estimated_start_date": task.estimated_start_date.isoformat()},
        skip_scheduling=True,
    )

    assert task.notified is True
    assert task.lastMinuteNotified is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    [
        {"title": "Otro título"},
        {"estimated_end_date": (_now() + timedelta(hours=5)).isoformat()},
    ],
)
async def test_other_changes_do_not_repeat_a_reminder(change):
    task = _task()

    await _service(task).update("t1", change, skip_scheduling=True)

    assert task.notified is True
    assert task.lastMinuteNotified is True


# ── Which tasks the sweep looks at ───────────────────────────────────────────


def test_finished_and_archived_tasks_get_no_reminders():
    # "Done" and "Archived" are the statuses the app sets.
    for status in ("Done", "Archived", "completed", "cancelled", "Completed"):
        assert status in INACTIVE_STATUSES
    for status in ("Backlog", "Todo", "Scheduled", "In Progress"):
        assert status not in INACTIVE_STATUSES


@pytest.mark.anyio
@pytest.mark.parametrize("is_last_minute", [False, True])
async def test_the_warning_query_leaves_out_inactive_and_deleted(is_last_minute):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    await TasksRepository(db).get_tasks_for_warning(4.0, 6.0, is_last_minute)

    stmt = db.execute.call_args.args[0]
    sql = str(stmt).lower()
    params = stmt.compile().params
    assert '"deletedat" is null' in sql
    assert "not in" in sql
    assert any(
        isinstance(v, (list, tuple)) and "Done" in v and "Archived" in v
        for v in params.values()
    )
    where = sql.split("where", 1)[1]
    assert ("lastminutenotified" in where) is is_last_minute
    assert ('"task".notified' in where) is not is_last_minute


# ── The sweep ────────────────────────────────────────────────────────────────


class _Session:
    def __init__(self):
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _sweep(monkeypatch, five=(), one=(), emit=None):
    session = _Session()
    tasks_repo = MagicMock()
    tasks_repo.get_tasks_for_warning = AsyncMock(
        side_effect=lambda a, b, is_last_minute: list(one if is_last_minute else five)
    )
    tasks_repo.save = AsyncMock()
    notif_repo = MagicMock()
    notif_repo.create = AsyncMock()
    sio = SimpleNamespace(emit=emit or AsyncMock())

    monkeypatch.setattr(notifier, "async_session_local", lambda: session)
    monkeypatch.setattr(notifier, "TasksRepository", lambda db: tasks_repo)
    monkeypatch.setattr(notifier, "NotificationsRepository", lambda db: notif_repo)
    monkeypatch.setattr(notifier, "sio", sio)
    return SimpleNamespace(session=session, notif_repo=notif_repo, sio=sio)


@pytest.mark.anyio
async def test_sweep_warns_at_5_and_1_minutes_to_the_users_room(monkeypatch):
    soon = _task(
        id="a",
        notified=False,
        estimated_start_date=_now() + timedelta(minutes=5, seconds=30),
    )
    now_ = _task(
        id="b",
        title="Llamada",
        lastMinuteNotified=False,
        estimated_start_date=_now() + timedelta(minutes=1, seconds=30),
    )
    world = _sweep(monkeypatch, five=[(soon, None)], one=[(now_, None)])

    await notifier._check_and_notify_once()

    calls = world.sio.emit.await_args_list
    assert [c.args[0] for c in calls] == ["task_upcoming", "task_upcoming"]
    assert all(c.kwargs == {"room": "user_u1", "namespace": "/realtime"} for c in calls)
    first, second = calls[0].args[1], calls[1].args[1]
    assert first["taskId"] == "a" and first["type"] == "5min"
    assert first["minutesLeft"] == 5
    assert first["deadline"].endswith("Z")
    assert second["taskId"] == "b" and second["type"] == "1min"
    assert second["minutesLeft"] == 1

    # Each warning only once, and it also lands in the notifications inbox.
    assert soon.notified is True
    assert now_.lastMinuteNotified is True
    assert world.notif_repo.create.await_count == 2
    world.session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_a_task_with_only_a_deadline_warns_from_the_deadline(monkeypatch):
    task = _task(
        notified=False,
        estimated_start_date=None,
        deadline=_now() + timedelta(minutes=5, seconds=30),
    )
    world = _sweep(monkeypatch, five=[(task, None)])

    await notifier._check_and_notify_once()

    payload = world.sio.emit.await_args.args[1]
    assert payload["deadline"] == task.deadline.isoformat() + "Z"


@pytest.mark.anyio
async def test_nothing_due_nothing_sent(monkeypatch):
    world = _sweep(monkeypatch)

    await notifier._check_and_notify_once()

    world.sio.emit.assert_not_awaited()
    world.session.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_a_failed_emit_is_logged_and_the_sweep_goes_on(monkeypatch, caplog):
    tasks = [
        (
            _task(
                id=i, notified=False, estimated_start_date=_now() + timedelta(minutes=5)
            ),
            None,
        )
        for i in ("a", "b")
    ]
    emit = AsyncMock(side_effect=[ConnectionError("redis down"), None])
    world = _sweep(monkeypatch, five=tasks, emit=emit)

    with caplog.at_level(logging.ERROR, logger=notifier.logger.name):
        await notifier._check_and_notify_once()

    assert emit.await_count == 2
    assert "task a" in caplog.text
    world.session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_the_loop_logs_a_failed_sweep_and_keeps_running(monkeypatch, caplog):
    sweeps = AsyncMock(side_effect=[RuntimeError("db gone"), None])
    sleeps = AsyncMock(side_effect=[None, StopAsyncIteration()])
    monkeypatch.setattr(notifier, "_check_and_notify_once", sweeps)
    monkeypatch.setattr(notifier.asyncio, "sleep", sleeps)
    monkeypatch.setattr(sweep_lock.cache, "acquire_lock", AsyncMock(return_value=True))

    with caplog.at_level(logging.ERROR, logger=notifier.logger.name):
        with pytest.raises(StopAsyncIteration):
            await notifier.run_task_notifier_loop()

    assert sweeps.await_count == 2
    assert "Task reminder sweep failed" in caplog.text
    assert "db gone" in caplog.text


# ── One sweep at a time (web replicas and/or the worker) ─────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize(
    "taken, runs",
    [(True, True), (False, False), (None, True)],
    ids=["lock taken", "another process has it", "redis down"],
)
async def test_a_sweep_runs_only_with_the_round_lock(monkeypatch, caplog, taken, runs):
    lock = AsyncMock(return_value=taken)
    monkeypatch.setattr(sweep_lock.cache, "acquire_lock", lock)
    sweep = AsyncMock()

    with caplog.at_level(logging.WARNING, logger=sweep_lock.logger.name):
        ran = await sweep_lock.run_exclusively("task_reminders", 55, sweep)

    assert ran is runs
    assert sweep.await_count == (1 if runs else 0)
    lock.assert_awaited_once_with("lock:notifier:task_reminders", 55)
    assert ("without a lock" in caplog.text) is (taken is None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "module, loop, name, ttl, interval",
    [
        (notifier, "run_task_notifier_loop", "task_reminders", 55, 60),
        (smart, "run_smart_notifier_loop", "smart_notifications", 290, 300),
    ],
)
async def test_each_loop_locks_a_little_under_its_interval(
    monkeypatch, module, loop, name, ttl, interval
):
    lock = AsyncMock(return_value=False)  # someone else sweeps this round
    sleeps = AsyncMock(side_effect=StopAsyncIteration())
    monkeypatch.setattr(sweep_lock.cache, "acquire_lock", lock)
    monkeypatch.setattr(module.asyncio, "sleep", sleeps)

    with pytest.raises(StopAsyncIteration):
        await getattr(module, loop)()

    lock.assert_awaited_once_with(f"lock:notifier:{name}", ttl)
    sleeps.assert_awaited_once_with(interval)
    assert ttl < interval


class _FakeRedis:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def set(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


@pytest.mark.anyio
@pytest.mark.parametrize(
    "client, expected",
    [
        (_FakeRedis(result=True), True),
        (_FakeRedis(result=None), False),  # SET NX on a held key
        (_FakeRedis(error=ConnectionError("reset")), None),
        (None, None),
    ],
    ids=["free", "held", "error", "disconnected"],
)
async def test_the_redis_lock(monkeypatch, client, expected):
    cache = ResilientRedisCache("redis://unused")
    cache.client = client
    monkeypatch.setattr(
        cache, "_ensure_connected", AsyncMock(return_value=client is not None)
    )

    assert await cache.acquire_lock("lock:x", 55) is expected
    if isinstance(client, _FakeRedis):
        assert client.calls == [(("lock:x", "1"), {"nx": True, "ex": 55})]


@pytest.mark.anyio
async def test_the_web_starts_both_loops_and_can_stop_them(monkeypatch):
    import asyncio

    import app.main as main

    started = []

    async def forever(name):
        started.append(name)
        await asyncio.Event().wait()

    monkeypatch.setattr(notifier, "run_task_notifier_loop", lambda: forever("task"))
    monkeypatch.setattr(smart, "run_smart_notifier_loop", lambda: forever("smart"))

    loops = main.start_notifier_loops()
    await asyncio.sleep(0)
    assert sorted(started) == ["smart", "task"]
    assert sorted(t.get_name() for t in loops) == [
        "smart-notifications",
        "task-reminders",
    ]

    for loop in loops:
        loop.cancel()
    await asyncio.gather(*loops, return_exceptions=True)
    assert all(t.cancelled() for t in loops)
