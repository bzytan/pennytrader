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
