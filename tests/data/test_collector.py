import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from data.collector import Collector
from data.store import DataStore
from engine.config import HistoryConfig, OptionsConfig


@pytest.fixture
def store(tmp_path: Path) -> DataStore:
    s = DataStore(tmp_path)
    s.ensure_dirs()
    return s


@pytest.fixture
def market_data():
    md = MagicMock()
    md.get_quote = AsyncMock(return_value={
        "symbol": "AAPL", "last_price": 150.0, "bid_price": 149.9,
        "ask_price": 150.1, "open_price": 148.0, "high_price": 152.0,
        "low_price": 147.0, "volume": 1_000_000,
    })
    md.get_price_history = AsyncMock(return_value=[
        {"time": "2024-01-16 09:30:00", "open": 148.0, "close": 148.5,
         "high": 148.7, "low": 147.9, "volume": 12000, "turnover": 1782000.0},
    ])
    return md


@pytest.fixture
def options():
    o = MagicMock()
    o.get_option_chain = AsyncMock(return_value=[
        {"contract": "US.AAPL240119C00150000", "option_type": "CALL",
         "strike_price": 150.0, "expiry": "2024-01-19", "lot_size": 100,
         "implied_volatility": 0.25, "delta": 0.55, "gamma": 0.03,
         "theta": -0.05, "vega": 0.12},
    ])
    return o


@pytest.fixture
def account():
    a = MagicMock()
    a.get_positions = AsyncMock(return_value=[])
    a.get_balance = AsyncMock(return_value={
        "cash": 10000.0, "buying_power": 20000.0,
        "total_assets": 30000.0, "market_value": 20000.0, "currency": "USD",
    })
    return a


@pytest.fixture
def orders():
    o = MagicMock()
    o.get_orders = AsyncMock(return_value=[])
    return o


@pytest.fixture
def history_config():
    return HistoryConfig(interval="1m", lookback_hours=6.5)


@pytest.fixture
def options_config():
    return OptionsConfig(nearest_expiries=2)


async def test_collect_writes_quote_file(
    store, market_data, options, account, orders, history_config, options_config,
):
    collector = Collector(
        store=store, market_data=market_data, options=options,
        account=account, orders=orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=lambda symbol, n: [date(2024, 1, 19)],
    )
    await collector.collect(["AAPL"], now=datetime(2024, 1, 16, 10, 30))

    quote = json.loads(store.quote_path("AAPL").read_text())
    assert quote["symbol"] == "AAPL"
    assert quote["last_price"] == 150.0


async def test_collect_writes_history_csv(
    store, market_data, options, account, orders, history_config, options_config,
):
    collector = Collector(
        store=store, market_data=market_data, options=options,
        account=account, orders=orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=lambda symbol, n: [date(2024, 1, 19)],
    )
    await collector.collect(["AAPL"], now=datetime(2024, 1, 16, 10, 30))

    text = store.history_path("AAPL", "1m").read_text()
    assert "time,open,close,high,low,volume,turnover" in text
    assert "148.0" in text


async def test_collect_writes_option_chain(
    store, market_data, options, account, orders, history_config, options_config,
):
    collector = Collector(
        store=store, market_data=market_data, options=options,
        account=account, orders=orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=lambda symbol, n: [date(2024, 1, 19)],
    )
    await collector.collect(["AAPL"], now=datetime(2024, 1, 16, 10, 30))

    chain_path = store.option_chain_path("AAPL", date(2024, 1, 19))
    chain = json.loads(chain_path.read_text())
    assert chain[0]["contract"] == "US.AAPL240119C00150000"


async def test_collect_writes_account_files(
    store, market_data, options, account, orders, history_config, options_config,
):
    collector = Collector(
        store=store, market_data=market_data, options=options,
        account=account, orders=orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=lambda symbol, n: [date(2024, 1, 19)],
    )
    await collector.collect(["AAPL"], now=datetime(2024, 1, 16, 10, 30))

    balance = json.loads(store.balance_path().read_text())
    assert balance["cash"] == 10000.0
    positions = json.loads(store.positions_path().read_text())
    assert positions == []
    open_orders = json.loads(store.open_orders_path().read_text())
    assert open_orders == []


async def test_collect_handles_multiple_symbols(
    store, market_data, options, account, orders, history_config, options_config,
):
    collector = Collector(
        store=store, market_data=market_data, options=options,
        account=account, orders=orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=lambda symbol, n: [date(2024, 1, 19)],
    )
    await collector.collect(["AAPL", "SPY"], now=datetime(2024, 1, 16, 10, 30))

    assert store.quote_path("AAPL").exists()
    assert store.quote_path("SPY").exists()
