from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.broker import BacktestBroker
from backtest.cache import HistoricalDataCache
from backtest.clock import SimulatedClock
from connector.exceptions import MoomooOrderError
from connector.orders import OrderSpec, OrderStatus, OrderType, OptionType, TradeSide


@pytest.fixture
async def cache_with_aapl(tmp_path):
    cache = HistoricalDataCache(cache_dir=tmp_path)
    md = MagicMock()
    md.get_price_history = AsyncMock(return_value=[
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
        {"time": "2026-01-15 09:31:00", "open": 101.0, "close": 99.0,
         "high": 101.5, "low": 98.5, "volume": 1100, "turnover": 110000.0},
    ])
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))
    return cache


@pytest.fixture
def clock():
    return SimulatedClock(start=datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")))


@pytest.fixture
def broker(cache_with_aapl, clock):
    return BacktestBroker(
        cache=cache_with_aapl, clock=clock,
        watchlist=["AAPL"], interval="1m", starting_cash=100000.0,
    )


async def test_get_balance_returns_starting_cash_initially(broker):
    bal = await broker.account.get_balance()
    assert bal["cash"] == 100000.0
    assert bal["total_assets"] == 100000.0


async def test_get_quote_returns_most_recent_bar_close(broker, clock):
    clock.set(datetime(2026, 1, 15, 9, 32, tzinfo=ZoneInfo("America/New_York")))
    quote = await broker.market_data.get_quote("AAPL")
    assert quote["last_price"] == 99.0


async def test_place_option_order_rejected(broker):
    spec = OrderSpec(
        symbol="US.AAPL240119C00150000", qty=1, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=5.50,
        expiry=date(2024, 1, 19), strike=150.0,
        option_type=OptionType.CALL, contract_size=100,
    )
    with pytest.raises(MoomooOrderError, match="stock-only"):
        await broker.orders.place_order(spec)


async def test_place_stock_order_returns_synthetic_id(broker):
    spec = OrderSpec(
        symbol="AAPL", qty=10, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=100.0,
    )
    order_id = await broker.orders.place_order(spec)
    assert order_id.startswith("BT-")


async def test_process_bar_fills_pending_limit_order(broker, clock):
    spec = OrderSpec(
        symbol="AAPL", qty=10, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=100.0,
    )
    await broker.orders.place_order(spec)
    clock.set(datetime(2026, 1, 15, 9, 32, tzinfo=ZoneInfo("America/New_York")))
    broker.process_bar(clock.now())
    filled = await broker.orders.get_orders(OrderStatus.FILLED)
    assert len(filled) == 1
    assert filled[0]["filled_qty"] == 10


async def test_subscribe_fills_callback_fires(broker, clock):
    received = []
    await broker.orders.subscribe_fills(lambda fill: received.append(fill))
    spec = OrderSpec(
        symbol="AAPL", qty=10, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=100.0,
    )
    await broker.orders.place_order(spec)
    clock.set(datetime(2026, 1, 15, 9, 32, tzinfo=ZoneInfo("America/New_York")))
    broker.process_bar(clock.now())
    assert len(received) == 1
    assert received[0]["symbol"] == "AAPL"


async def test_position_reflects_filled_buy(broker, clock):
    spec = OrderSpec(
        symbol="AAPL", qty=10, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=100.0,
    )
    await broker.orders.place_order(spec)
    clock.set(datetime(2026, 1, 15, 9, 32, tzinfo=ZoneInfo("America/New_York")))
    broker.process_bar(clock.now())
    positions = await broker.account.get_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["qty"] == 10


async def test_balance_after_buy_reduces_cash_and_adds_market_value(broker, clock):
    spec = OrderSpec(
        symbol="AAPL", qty=10, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=100.0,
    )
    await broker.orders.place_order(spec)
    clock.set(datetime(2026, 1, 15, 9, 32, tzinfo=ZoneInfo("America/New_York")))
    broker.process_bar(clock.now())
    bal = await broker.account.get_balance()
    assert bal["cash"] == 100000.0 - 1000.0
    assert bal["market_value"] == 10 * 99.0


async def test_get_trading_days_derives_from_cache(broker):
    days = await broker.market_data.get_trading_days("US", date(2026, 1, 15), date(2026, 1, 15))
    assert len(days) == 1
    assert days[0]["date"] == date(2026, 1, 15)
    assert days[0]["type"] == "WHOLE"


async def test_get_account_info_marks_environment_backtest(broker):
    info = await broker.account.get_account_info()
    assert info["environment"] == "backtest"


async def test_get_option_chain_raises(broker):
    from connector.exceptions import MoomooMarketDataError
    with pytest.raises(MoomooMarketDataError, match="options not supported"):
        await broker.market_data.get_option_chain("AAPL", date(2024, 1, 19))
