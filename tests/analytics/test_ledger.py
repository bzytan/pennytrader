import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from analytics.ledger import Ledger
from data.store import DataStore


@pytest.fixture
def store(tmp_path):
    s = DataStore(tmp_path)
    s.ensure_dirs()
    return s


def _filled(order_id, code, side, qty, price, when):
    return {
        "order_id": order_id, "symbol": code, "side": side,
        "qty": qty, "price": price, "filled_qty": qty,
        "avg_fill_price": price, "created_at": when,
        "status": "filled", "name": "n/a", "order_type": "limit",
    }


def _orders_returning(filled_orders):
    o = MagicMock()
    o.get_orders = AsyncMock(return_value=filled_orders)
    return o


def _account_with_balance(total_assets, cash, market_value):
    a = MagicMock()
    a.get_balance = AsyncMock(return_value={
        "cash": cash, "buying_power": cash * 2,
        "total_assets": total_assets, "market_value": market_value,
        "currency": "USD",
    })
    return a


async def test_rebuild_with_no_orders_writes_empty_trades(store):
    orders = _orders_returning([])
    account = _account_with_balance(100000.0, 100000.0, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 4))
    text = store.trades_path().read_text()
    assert text == ""


async def test_rebuild_writes_equity_curve_entry(store):
    orders = _orders_returning([])
    account = _account_with_balance(100000.0, 100000.0, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 4))
    lines = store.equity_curve_path().read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["date"] == "2026-05-04"
    assert entry["total_assets"] == 100000.0


async def test_rebuild_appends_new_equity_entries(store):
    orders = _orders_returning([])
    account = _account_with_balance(100000.0, 100000.0, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 3))

    account = _account_with_balance(101000.0, 50000.0, 51000.0)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 4))
    lines = store.equity_curve_path().read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["total_assets"] == 101000.0


async def test_rebuild_replaces_same_date_equity_entry(store):
    orders = _orders_returning([])
    account = _account_with_balance(100000.0, 100000.0, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 3))

    account = _account_with_balance(100500.0, 100500.0, 0.0)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 3))
    lines = store.equity_curve_path().read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["total_assets"] == 100500.0


async def test_rebuild_matches_single_buy_sell(store):
    orders = _orders_returning([
        _filled("O1", "US.AAPL", "BUY", 10, 150.0, "2026-05-01 10:00:00"),
        _filled("O2", "US.AAPL", "SELL", 10, 155.0, "2026-05-02 14:00:00"),
    ])
    account = _account_with_balance(100050.0, 100050.0, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 4))

    trades = [json.loads(l) for l in store.trades_path().read_text().splitlines()]
    assert len(trades) == 1
    t = trades[0]
    assert t["symbol"] == "US.AAPL"
    assert t["side"] == "long"
    assert t["qty"] == 10
    assert t["entry_price"] == 150.0
    assert t["exit_price"] == 155.0
    assert t["pnl"] == 50.0
    assert t["holding_period_days"] == 1
    assert t["is_option"] is False


async def test_rebuild_handles_partial_fills_fifo(store):
    orders = _orders_returning([
        _filled("O1", "US.AAPL", "BUY", 10, 150.0, "2026-05-01 10:00:00"),
        _filled("O2", "US.AAPL", "SELL", 4, 155.0, "2026-05-02 11:00:00"),
        _filled("O3", "US.AAPL", "SELL", 6, 160.0, "2026-05-03 11:00:00"),
    ])
    account = _account_with_balance(100080.0, 100080.0, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 4))

    trades = [json.loads(l) for l in store.trades_path().read_text().splitlines()]
    assert len(trades) == 2
    # First trade: 4 shares @ 150 → 155
    assert trades[0]["qty"] == 4
    assert trades[0]["pnl"] == 4 * (155.0 - 150.0)
    # Second trade: 6 shares @ 150 → 160
    assert trades[1]["qty"] == 6
    assert trades[1]["pnl"] == 6 * (160.0 - 150.0)


async def test_rebuild_separates_symbols(store):
    orders = _orders_returning([
        _filled("O1", "US.AAPL", "BUY", 10, 150.0, "2026-05-01 10:00:00"),
        _filled("O2", "US.SPY", "BUY", 5, 400.0, "2026-05-01 10:30:00"),
        _filled("O3", "US.AAPL", "SELL", 10, 155.0, "2026-05-02 14:00:00"),
        _filled("O4", "US.SPY", "SELL", 5, 410.0, "2026-05-02 15:00:00"),
    ])
    account = _account_with_balance(100100.0, 100100.0, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 4))

    trades = [json.loads(l) for l in store.trades_path().read_text().splitlines()]
    assert len(trades) == 2
    by_sym = {t["symbol"]: t for t in trades}
    assert by_sym["US.AAPL"]["pnl"] == 50.0
    assert by_sym["US.SPY"]["pnl"] == 50.0


async def test_rebuild_marks_option_trades(store):
    orders = _orders_returning([
        _filled("O1", "US.AAPL240119C00150000", "BUY", 1, 5.50, "2026-05-01 10:00:00"),
        _filled("O2", "US.AAPL240119C00150000", "SELL", 1, 6.00, "2026-05-02 14:00:00"),
    ])
    account = _account_with_balance(100000.50, 100000.50, 0.0)
    ledger = Ledger(store=store)
    await ledger.rebuild(orders=orders, account=account, today=date(2026, 5, 4))

    trades = [json.loads(l) for l in store.trades_path().read_text().splitlines()]
    assert trades[0]["is_option"] is True
