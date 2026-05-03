import json
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.dream import DreamRunner
from agent.runner import AgentResult
from data.store import DataStore


@pytest.fixture
def store(tmp_path):
    s = DataStore(tmp_path)
    s.ensure_dirs()
    return s


@pytest.fixture
def deps(store):
    ledger = MagicMock()
    ledger.rebuild = AsyncMock()
    performance_fn = AsyncMock(return_value={"as_of": "2026-05-04"})
    runner = MagicMock()
    runner.run = AsyncMock(return_value=AgentResult(
        exit_code=0, stdout="dream done", stderr="",
        duration_seconds=1.0, timed_out=False,
    ))
    log_writer = MagicMock()
    account = MagicMock()
    orders = MagicMock()
    return ledger, performance_fn, runner, log_writer, account, orders, store


async def test_run_calls_ledger_then_performance_then_runner(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps
    store.atomic_write_text(store.learnings_path(),
        json.dumps({"id": "l1", "created_at": "2026-05-04T08:00:00",
                    "category": "general", "observation": "test",
                    "evidence": "test", "active": True}) + "\n",
    )
    store.atomic_write_text(store.dream_path(date(2026, 5, 4)), "x" * 250)
    dreamer = DreamRunner(
        ledger=ledger, performance_fn=performance_fn,
        runner=runner, store=store, log_writer=log_writer,
        account=account, orders=orders,
    )
    ok = await dreamer.run(now=datetime(2026, 5, 4, 8, 0))
    assert ok is True
    ledger.rebuild.assert_awaited_once()
    performance_fn.assert_awaited_once()
    runner.run.assert_awaited_once()


async def test_run_writes_last_dream_on_success(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps
    store.atomic_write_text(store.learnings_path(),
        json.dumps({"id": "l1", "created_at": "2026-05-04T08:00:00",
                    "category": "general", "observation": "test",
                    "evidence": "test", "active": True}) + "\n",
    )
    store.atomic_write_text(store.dream_path(date(2026, 5, 4)), "x" * 250)
    dreamer = DreamRunner(
        ledger=ledger, performance_fn=performance_fn,
        runner=runner, store=store, log_writer=log_writer,
        account=account, orders=orders,
    )
    await dreamer.run(now=datetime(2026, 5, 4, 8, 0))
    assert store.last_dream_path().read_text().strip() == "2026-05-04"


async def test_run_returns_false_when_subprocess_fails(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps
    runner.run = AsyncMock(return_value=AgentResult(
        exit_code=1, stdout="", stderr="boom",
        duration_seconds=0.0, timed_out=False,
    ))
    dreamer = DreamRunner(
        ledger=ledger, performance_fn=performance_fn,
        runner=runner, store=store, log_writer=log_writer,
        account=account, orders=orders,
    )
    ok = await dreamer.run(now=datetime(2026, 5, 4, 8, 0))
    assert ok is False
    assert not store.last_dream_path().exists()


async def test_run_rejects_missing_learnings_file(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps
    store.atomic_write_text(store.dream_path(date(2026, 5, 4)), "x" * 250)
    dreamer = DreamRunner(
        ledger=ledger, performance_fn=performance_fn,
        runner=runner, store=store, log_writer=log_writer,
        account=account, orders=orders,
    )
    ok = await dreamer.run(now=datetime(2026, 5, 4, 8, 0))
    assert ok is False
    log_events = [c.args[0]["event"] for c in log_writer.write.call_args_list]
    assert "dream_validation_failed" in log_events


async def test_run_rejects_majority_shrinkage(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps
    prior = "\n".join(
        json.dumps({"id": f"l{i}", "created_at": "2026-05-03T08:00",
                    "category": "general", "observation": "x", "evidence": "x",
                    "active": True})
        for i in range(10)
    ) + "\n"
    store.atomic_write_text(store.learnings_path(), prior)

    def write_shrunk(*_args, **_kwargs):
        new = "\n".join(
            json.dumps({"id": f"new{i}", "created_at": "2026-05-04T08:00",
                        "category": "general", "observation": "x",
                        "evidence": "x", "active": True})
            for i in range(3)
        ) + "\n"
        store.atomic_write_text(store.learnings_path(), new)
        return AgentResult(exit_code=0, stdout="ok", stderr="",
                            duration_seconds=1.0, timed_out=False)
    runner.run = AsyncMock(side_effect=write_shrunk)
    store.atomic_write_text(store.dream_path(date(2026, 5, 4)), "x" * 250)

    dreamer = DreamRunner(
        ledger=ledger, performance_fn=performance_fn,
        runner=runner, store=store, log_writer=log_writer,
        account=account, orders=orders,
    )
    ok = await dreamer.run(now=datetime(2026, 5, 4, 8, 0))
    assert ok is False
    lines = store.learnings_path().read_text().splitlines()
    assert len(lines) == 10
    log_events = [c.args[0]["event"] for c in log_writer.write.call_args_list]
    assert "dream_validation_failed" in log_events


async def test_run_rejects_entries_missing_required_fields(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps

    def write_invalid(*_args, **_kwargs):
        body = json.dumps({"id": "x", "created_at": "2026-05-04T08:00",
                           "category": "general", "observation": "x",
                           "active": True}) + "\n"
        store.atomic_write_text(store.learnings_path(), body)
        return AgentResult(exit_code=0, stdout="ok", stderr="",
                            duration_seconds=1.0, timed_out=False)
    runner.run = AsyncMock(side_effect=write_invalid)
    store.atomic_write_text(store.dream_path(date(2026, 5, 4)), "x" * 250)

    dreamer = DreamRunner(
        ledger=ledger, performance_fn=performance_fn,
        runner=runner, store=store, log_writer=log_writer,
        account=account, orders=orders,
    )
    ok = await dreamer.run(now=datetime(2026, 5, 4, 8, 0))
    assert ok is False
