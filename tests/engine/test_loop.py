from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from agent.runner import AgentResult
from engine.config import (
    Config, HistoryConfig, MarketHoursConfig, OptionsConfig, SafetyConfig,
)
from engine.loop import Engine


def _make_config(**overrides):
    base = Config(
        mode="paper",
        heartbeat_interval_seconds=60,
        claude_timeout_seconds=120,
        market_hours=MarketHoursConfig(open="09:30", close="16:00", tz="America/New_York"),
        watchlist=["AAPL"],
        history=HistoryConfig(interval="1m", lookback_hours=6.5),
        options=OptionsConfig(nearest_expiries=2),
        safety=SafetyConfig(
            max_position_size_pct=5.0,
            daily_loss_threshold_pct=5.0,
            max_consecutive_agent_failures=3,
        ),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


@pytest.fixture
def deps():
    collector = MagicMock()
    collector.collect = AsyncMock()
    runner = MagicMock()
    runner.run = AsyncMock(return_value=AgentResult(
        exit_code=0, stdout="ok", stderr="", duration_seconds=0.1, timed_out=False,
    ))
    prompt_builder = MagicMock()
    prompt_builder.build = MagicMock(return_value="prompt")
    account = MagicMock()
    account.get_balance = AsyncMock(return_value={
        "cash": 10000.0, "buying_power": 20000.0,
        "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD",
    })
    account.get_positions = AsyncMock(return_value=[])
    orders = MagicMock()
    orders.get_orders = AsyncMock(return_value=[])
    fill_buffer: list[dict] = []
    return collector, runner, prompt_builder, account, orders, fill_buffer


async def test_tick_invokes_collector_and_runner_when_open(deps):
    collector, runner, prompt_builder, account, orders, fill_buffer = deps
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer,
        log_writer=MagicMock(),
    )
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)
    collector.collect.assert_awaited_once_with(["AAPL"])
    runner.run.assert_awaited_once()


async def test_tick_skips_when_market_closed(deps):
    collector, runner, prompt_builder, account, orders, fill_buffer = deps
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, log_writer=MagicMock(),
    )
    closed_time = datetime(2024, 1, 16, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=closed_time)
    collector.collect.assert_not_awaited()
    runner.run.assert_not_awaited()


async def test_circuit_breaker_trips_on_excessive_loss(deps):
    collector, runner, prompt_builder, account, orders, fill_buffer = deps
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, log_writer=MagicMock(),
    )
    engine.set_baseline_total_assets(100000.0)
    account.get_balance = AsyncMock(return_value={
        "cash": 0.0, "buying_power": 0.0,
        "total_assets": 94000.0, "market_value": 94000.0, "currency": "USD",
    })  # -6%, exceeds 5%
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)
    assert engine.circuit_breaker_tripped is True
    runner.run.assert_not_awaited()


async def test_consecutive_agent_failures_halt_engine(deps):
    collector, runner, prompt_builder, account, orders, fill_buffer = deps
    config = _make_config()
    runner.run = AsyncMock(return_value=AgentResult(
        exit_code=1, stdout="", stderr="boom", duration_seconds=0.0, timed_out=False,
    ))
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, log_writer=MagicMock(),
    )
    engine.set_baseline_total_assets(100000.0)
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    for _ in range(3):
        await engine.tick(now=open_time)
    assert engine.halted is True
    assert runner.run.await_count == 3
    await engine.tick(now=open_time)
    assert runner.run.await_count == 3  # halted, no further calls


async def test_tick_drains_fill_buffer(deps):
    collector, runner, prompt_builder, account, orders, fill_buffer = deps
    fill_buffer.append({"order_id": "ORD001", "symbol": "US.AAPL",
                        "side": "BUY", "qty": 10, "price": 150.0,
                        "filled_at": "2024-01-16 10:00:00"})
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, log_writer=MagicMock(),
    )
    engine.set_baseline_total_assets(100000.0)
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)
    # buffer is drained
    assert fill_buffer == []
    # prompt_builder was called with the fill in recent_fills
    args, kwargs = prompt_builder.build.call_args
    assert kwargs["recent_fills"][0]["order_id"] == "ORD001"


async def test_baseline_auto_initializes_from_first_balance(deps):
    collector, runner, prompt_builder, account, orders, fill_buffer = deps
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, log_writer=MagicMock(),
    )
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)
    # baseline was None on entry; should be set to current total_assets
    assert engine._baseline_total_assets == 100000.0


async def test_collector_failure_preserves_fills_for_next_tick(deps):
    collector, runner, prompt_builder, account, orders, fill_buffer = deps
    fill_buffer.append({"order_id": "ORD001", "symbol": "US.AAPL",
                        "side": "BUY", "qty": 1, "price": 100.0,
                        "filled_at": "2024-01-16 10:00:00"})
    collector.collect = AsyncMock(side_effect=RuntimeError("network down"))
    config = _make_config()
    log_writer = MagicMock()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, log_writer=log_writer,
    )
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)
    # collector failed; fill should be back in the buffer
    assert len(fill_buffer) == 1
    assert fill_buffer[0]["order_id"] == "ORD001"
    runner.run.assert_not_awaited()
    # collector_error event was logged
    log_calls = [call.args[0]["event"] for call in log_writer.write.call_args_list]
    assert "collector_error" in log_calls
