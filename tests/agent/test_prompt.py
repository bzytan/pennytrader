from datetime import datetime
from pathlib import Path

from data.store import DataStore
from agent.prompt import PromptBuilder


def test_prompt_includes_system_role(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"], history_interval="1m")
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 10000.0, "buying_power": 20000.0,
                 "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD"},
        positions=[],
        open_orders=[],
        recent_fills=[],
        recent_order_updates=[],
        daily_pnl=0.0,
    )
    assert "autonomous trading agent" in prompt.lower()
    assert "proposed_trades" in prompt


def test_prompt_includes_account_state(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"], history_interval="1m")
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 10000.0, "buying_power": 20000.0,
                 "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD"},
        positions=[{"symbol": "US.AAPL", "qty": 10, "cost_price": 145.0}],
        open_orders=[],
        recent_fills=[],
        recent_order_updates=[],
        daily_pnl=250.0,
    )
    assert "10000.0" in prompt or "10,000" in prompt
    assert "US.AAPL" in prompt
    assert "250" in prompt


def test_prompt_includes_data_file_paths_for_each_watchlist_symbol(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL", "SPY"], history_interval="1m")
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[], recent_fills=[], recent_order_updates=[], daily_pnl=0.0,
    )
    assert str(store.quote_path("AAPL")) in prompt
    assert str(store.quote_path("SPY")) in prompt
    assert str(store.history_path("AAPL", "1m")) in prompt or "AAPL_" in prompt


def test_prompt_includes_recent_fills_when_present(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"], history_interval="1m")
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[],
        recent_fills=[{"order_id": "ORD001", "symbol": "US.AAPL",
                       "side": "BUY", "qty": 10, "price": 150.0,
                       "filled_at": "2024-01-16 10:00:00"}],
        recent_order_updates=[],
        daily_pnl=0.0,
    )
    assert "ORD001" in prompt
    assert "BUY" in prompt


def test_prompt_uses_configured_history_interval(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"], history_interval="5m")
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[], recent_fills=[], recent_order_updates=[], daily_pnl=0.0,
    )
    assert "AAPL_5m.csv" in prompt


def test_prompt_includes_recent_order_updates(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"], history_interval="1m")
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[],
        recent_fills=[],
        recent_order_updates=[{
            "order_id": "ORD001", "symbol": "US.AAPL", "side": "BUY",
            "qty": 10, "price": 150.0, "filled_qty": 0,
            "order_status": "FAILED", "updated_at": "2024-01-16 10:00:01",
        }],
        daily_pnl=0.0,
    )
    assert "ORD001" in prompt
    assert "FAILED" in prompt
    assert str(store.recent_order_updates_path()) in prompt
