import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from analytics.performance import compute_performance
from data.store import DataStore


@pytest.fixture
def store(tmp_path):
    s = DataStore(tmp_path)
    s.ensure_dirs()
    return s


def _write_trades(store, trades):
    body = "\n".join(json.dumps(t) for t in trades) + "\n" if trades else ""
    store.atomic_write_text(store.trades_path(), body)


def _write_equity(store, entries):
    body = "\n".join(json.dumps(e) for e in entries) + "\n" if entries else ""
    store.atomic_write_text(store.equity_curve_path(), body)


def _account_with_positions(positions, total_assets=100000.0):
    a = MagicMock()
    a.get_positions = AsyncMock(return_value=positions)
    a.get_balance = AsyncMock(return_value={
        "cash": 50000.0, "buying_power": 100000.0,
        "total_assets": total_assets, "market_value": 50000.0,
        "currency": "USD",
    })
    return a


async def test_compute_performance_with_no_data(store):
    _write_trades(store, [])
    _write_equity(store, [{"date": "2026-05-04", "total_assets": 100000.0,
                           "cash": 100000.0, "market_value": 0.0}])
    account = _account_with_positions([])
    perf = await compute_performance(store=store, account=account, today=date(2026, 5, 4))
    assert perf["as_of"] == "2026-05-04"
    assert perf["open_positions_unrealized_pnl"] == 0.0
    assert perf["all_time"]["realized_pnl"] == 0
    assert perf["all_time"]["trades_closed"] == 0
    assert perf["by_symbol"] == {}


async def test_compute_performance_aggregates_by_window(store):
    _write_trades(store, [
        {"symbol": "US.AAPL", "side": "long", "qty": 10,
         "entry_date": "2026-05-04", "entry_price": 150.0,
         "exit_date": "2026-05-04", "exit_price": 160.0,
         "pnl": 100.0, "holding_period_days": 0, "is_option": False},
        {"symbol": "US.AAPL", "side": "long", "qty": 5,
         "entry_date": "2026-04-30", "entry_price": 150.0,
         "exit_date": "2026-05-01", "exit_price": 140.0,
         "pnl": -50.0, "holding_period_days": 1, "is_option": False},
        {"symbol": "US.SPY", "side": "long", "qty": 5,
         "entry_date": "2026-04-15", "entry_price": 400.0,
         "exit_date": "2026-04-20", "exit_price": 440.0,
         "pnl": 200.0, "holding_period_days": 5, "is_option": False},
    ])
    _write_equity(store, [
        {"date": "2026-04-15", "total_assets": 100000.0, "cash": 100000.0, "market_value": 0.0},
        {"date": "2026-05-04", "total_assets": 100250.0, "cash": 100250.0, "market_value": 0.0},
    ])
    account = _account_with_positions([])
    perf = await compute_performance(store=store, account=account, today=date(2026, 5, 4))

    assert perf["today"]["realized_pnl"] == 100.0
    assert perf["today"]["trades_closed"] == 1
    assert perf["last_7_days"]["realized_pnl"] == 50.0
    assert perf["last_7_days"]["trades_closed"] == 2
    assert perf["last_30_days"]["realized_pnl"] == 250.0
    assert perf["last_30_days"]["trades_closed"] == 3
    assert perf["all_time"]["realized_pnl"] == 250.0
    assert perf["all_time"]["trades_closed"] == 3


async def test_compute_performance_win_rate_and_averages(store):
    _write_trades(store, [
        {"symbol": "US.AAPL", "side": "long", "qty": 1,
         "entry_date": "2026-05-01", "entry_price": 100.0,
         "exit_date": "2026-05-01", "exit_price": 110.0,
         "pnl": 10.0, "holding_period_days": 0, "is_option": False},
        {"symbol": "US.AAPL", "side": "long", "qty": 1,
         "entry_date": "2026-05-02", "entry_price": 100.0,
         "exit_date": "2026-05-02", "exit_price": 120.0,
         "pnl": 20.0, "holding_period_days": 0, "is_option": False},
        {"symbol": "US.AAPL", "side": "long", "qty": 1,
         "entry_date": "2026-05-03", "entry_price": 100.0,
         "exit_date": "2026-05-03", "exit_price": 90.0,
         "pnl": -10.0, "holding_period_days": 0, "is_option": False},
    ])
    _write_equity(store, [{"date": "2026-05-04", "total_assets": 100020.0,
                           "cash": 100020.0, "market_value": 0.0}])
    account = _account_with_positions([])
    perf = await compute_performance(store=store, account=account, today=date(2026, 5, 4))
    assert perf["all_time"]["win_rate"] == pytest.approx(2 / 3)
    assert perf["all_time"]["avg_winner"] == 15.0
    assert perf["all_time"]["avg_loser"] == -10.0


async def test_compute_performance_per_symbol_breakdown(store):
    _write_trades(store, [
        {"symbol": "US.AAPL", "side": "long", "qty": 1,
         "entry_date": "2026-05-01", "entry_price": 100.0,
         "exit_date": "2026-05-01", "exit_price": 110.0,
         "pnl": 10.0, "holding_period_days": 0, "is_option": False},
        {"symbol": "US.SPY", "side": "long", "qty": 1,
         "entry_date": "2026-05-02", "entry_price": 400.0,
         "exit_date": "2026-05-02", "exit_price": 380.0,
         "pnl": -20.0, "holding_period_days": 0, "is_option": False},
    ])
    _write_equity(store, [{"date": "2026-05-04", "total_assets": 99990.0,
                           "cash": 99990.0, "market_value": 0.0}])
    account = _account_with_positions([])
    perf = await compute_performance(store=store, account=account, today=date(2026, 5, 4))
    assert perf["by_symbol"]["US.AAPL"]["realized_pnl"] == 10.0
    assert perf["by_symbol"]["US.SPY"]["realized_pnl"] == -20.0


async def test_compute_performance_open_positions_unrealized(store):
    _write_trades(store, [])
    _write_equity(store, [{"date": "2026-05-04", "total_assets": 100200.0,
                           "cash": 99000.0, "market_value": 1200.0}])
    account = _account_with_positions([
        {"symbol": "US.AAPL", "qty": 10, "cost_price": 100.0,
         "current_price": 120.0, "market_value": 1200.0,
         "unrealized_pl": 200.0, "is_option": False, "name": "Apple",
         "currency": "USD", "side": "LONG"},
    ])
    perf = await compute_performance(store=store, account=account, today=date(2026, 5, 4))
    assert perf["open_positions_unrealized_pnl"] == 200.0


async def test_compute_performance_max_drawdown(store):
    _write_trades(store, [])
    _write_equity(store, [
        {"date": "2026-04-15", "total_assets": 100000.0, "cash": 100000.0, "market_value": 0.0},
        {"date": "2026-04-20", "total_assets": 110000.0, "cash": 110000.0, "market_value": 0.0},
        {"date": "2026-04-25", "total_assets": 95000.0, "cash": 95000.0, "market_value": 0.0},
        {"date": "2026-05-04", "total_assets": 105000.0, "cash": 105000.0, "market_value": 0.0},
    ])
    account = _account_with_positions([])
    perf = await compute_performance(store=store, account=account, today=date(2026, 5, 4))
    assert perf["last_30_days"]["max_drawdown_pct"] == pytest.approx(13.6363636, rel=1e-3)
