import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from agent.runner import AgentResult
from backtest.clock import SimulatedClock
from backtest.runner import BacktestRunner


@pytest.fixture
def deps(tmp_path):
    broker = MagicMock()
    broker.process_bar = MagicMock()
    engine = MagicMock()
    engine.tick = AsyncMock()
    engine.run_dream_if_due = AsyncMock()
    engine.halted = False
    calendar = MagicMock()
    calendar.is_trading_day = MagicMock(return_value=True)
    calendar.session_type = MagicMock(return_value="WHOLE")
    market_hours = MagicMock(open="09:30", close="16:00", early_close="13:00", tz="America/New_York")
    return broker, engine, calendar, market_hours, tmp_path


async def test_runner_advances_clock_and_calls_tick(deps):
    broker, engine, calendar, market_hours, run_dir = deps
    clock = SimulatedClock(start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    runner = BacktestRunner(
        broker=broker, engine=engine, clock=clock, calendar=calendar,
        market_hours=market_hours, run_dir=run_dir,
        start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        end=datetime(2026, 1, 15, 9, 45, tzinfo=ZoneInfo("America/New_York")),
        heartbeat_minutes=5, dream_every_n_days=7,
    )
    await runner.run()
    assert engine.tick.await_count >= 3
    broker.process_bar.assert_called()


async def test_runner_writes_manifest(deps):
    broker, engine, calendar, market_hours, run_dir = deps
    clock = SimulatedClock(start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    runner = BacktestRunner(
        broker=broker, engine=engine, clock=clock, calendar=calendar,
        market_hours=market_hours, run_dir=run_dir,
        start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        end=datetime(2026, 1, 15, 9, 35, tzinfo=ZoneInfo("America/New_York")),
        heartbeat_minutes=5, dream_every_n_days=7,
    )
    await runner.run()
    manifest_path = run_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert "start" in manifest
    assert "end" in manifest


async def test_runner_runs_final_dream_at_end(deps):
    broker, engine, calendar, market_hours, run_dir = deps
    clock = SimulatedClock(start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    runner = BacktestRunner(
        broker=broker, engine=engine, clock=clock, calendar=calendar,
        market_hours=market_hours, run_dir=run_dir,
        start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        end=datetime(2026, 1, 15, 9, 35, tzinfo=ZoneInfo("America/New_York")),
        heartbeat_minutes=5, dream_every_n_days=7,
    )
    await runner.run()
    assert engine.run_dream_if_due.await_count >= 1


async def test_runner_skips_non_trading_days(deps):
    broker, engine, calendar, market_hours, run_dir = deps
    calendar.is_trading_day = MagicMock(side_effect=lambda d: d.isoformat() != "2026-01-15")
    clock = SimulatedClock(start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    runner = BacktestRunner(
        broker=broker, engine=engine, clock=clock, calendar=calendar,
        market_hours=market_hours, run_dir=run_dir,
        start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        end=datetime(2026, 1, 16, 9, 35, tzinfo=ZoneInfo("America/New_York")),
        heartbeat_minutes=5, dream_every_n_days=7,
    )
    await runner.run()
    tick_dates = {call.kwargs["now"].date().isoformat() for call in engine.tick.await_args_list}
    assert "2026-01-15" not in tick_dates
    assert "2026-01-16" in tick_dates


async def test_runner_stops_when_engine_halted(deps):
    broker, engine, calendar, market_hours, run_dir = deps
    halts = iter([False, True])
    type(engine).halted = property(lambda self: next(halts, True))
    clock = SimulatedClock(start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    runner = BacktestRunner(
        broker=broker, engine=engine, clock=clock, calendar=calendar,
        market_hours=market_hours, run_dir=run_dir,
        start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        end=datetime(2026, 1, 15, 16, 0, tzinfo=ZoneInfo("America/New_York")),
        heartbeat_minutes=5, dream_every_n_days=7,
    )
    await runner.run()
    assert engine.tick.await_count < 10
