from pathlib import Path

from data.store import DataStore


def test_store_creates_subdirs(tmp_path):
    store = DataStore(tmp_path)
    store.ensure_dirs()
    for sub in ("quotes", "history", "options", "account", "log"):
        assert (tmp_path / sub).is_dir()


def test_quote_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.quote_path("AAPL") == tmp_path / "quotes" / "AAPL.json"


def test_history_path_includes_interval(tmp_path):
    store = DataStore(tmp_path)
    assert store.history_path("AAPL", "1m") == tmp_path / "history" / "AAPL_1m.csv"


def test_option_chain_path_includes_expiry(tmp_path):
    from datetime import date
    store = DataStore(tmp_path)
    assert store.option_chain_path("AAPL", date(2024, 1, 19)) == (
        tmp_path / "options" / "AAPL_2024-01-19.json"
    )


def test_account_paths(tmp_path):
    store = DataStore(tmp_path)
    assert store.positions_path() == tmp_path / "account" / "positions.json"
    assert store.balance_path() == tmp_path / "account" / "balance.json"
    assert store.open_orders_path() == tmp_path / "account" / "orders_open.json"
    assert store.recent_fills_path() == tmp_path / "account" / "recent_fills.json"


def test_proposed_trades_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.proposed_trades_path() == tmp_path / "account" / "proposed_trades.jsonl"


def test_proposal_results_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.proposal_results_path() == tmp_path / "account" / "recent_proposal_results.json"


def test_recent_order_updates_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.recent_order_updates_path() == (
        tmp_path / "account" / "recent_order_updates.json"
    )


def test_decision_log_path_uses_date(tmp_path):
    from datetime import date
    store = DataStore(tmp_path)
    assert store.decision_log_path(date(2024, 1, 16)) == (
        tmp_path / "log" / "decisions-2024-01-16.jsonl"
    )


def test_atomic_write_text(tmp_path):
    store = DataStore(tmp_path)
    target = tmp_path / "x.txt"
    store.atomic_write_text(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_replaces_existing(tmp_path):
    store = DataStore(tmp_path)
    target = tmp_path / "x.txt"
    target.write_text("old")
    store.atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_trades_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.trades_path() == tmp_path / "ledger" / "trades.jsonl"


def test_equity_curve_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.equity_curve_path() == tmp_path / "ledger" / "equity_curve.jsonl"


def test_performance_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.performance_path() == tmp_path / "performance.json"


def test_learnings_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.learnings_path() == tmp_path / "learnings" / "learnings.jsonl"


def test_dream_path_uses_date(tmp_path):
    from datetime import date
    store = DataStore(tmp_path)
    assert store.dream_path(date(2026, 5, 4)) == tmp_path / "dreams" / "2026-05-04.md"


def test_last_dream_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.last_dream_path() == tmp_path / "last_dream.txt"


def test_ensure_dirs_creates_new_subdirs(tmp_path):
    store = DataStore(tmp_path)
    store.ensure_dirs()
    for sub in ("ledger", "learnings", "dreams"):
        assert (tmp_path / sub).is_dir()


def test_history_cache_dir(tmp_path):
    store = DataStore(tmp_path)
    assert store.history_cache_dir() == tmp_path / "historical_cache"


def test_backtest_run_dir(tmp_path):
    store = DataStore(tmp_path)
    assert store.backtest_run_dir("2026-05-04T22-15-00_label") == (
        tmp_path / "backtests" / "2026-05-04T22-15-00_label"
    )
