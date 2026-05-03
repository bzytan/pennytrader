# Performance Analytics + Self-Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a trade ledger, performance metrics, persistent structured learnings, and a daily pre-market "dream" reflection cycle so the autonomous agent can evolve its strategies over time.

**Architecture:** A new `analytics/` package owns the deterministic computation (Ledger, Performance, LearningsStore). A new `agent/dream.py` orchestrates the dream cycle: rebuild ledger from broker data, recompute performance, invoke `claude --print` with a reflection prompt, validate outputs, and update the learnings file. The engine triggers the dream once per day before the first trading tick.

**Tech Stack:** Python 3.11+, moomoo-api, pytest, pytest-asyncio. Reuses existing `AgentRunner` for the dream subprocess.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `analytics/__init__.py` | Create | Package marker |
| `tests/analytics/__init__.py` | Create | Test package marker |
| `data/store.py` | Modify | Add paths for ledger, performance, learnings, dreams, last_dream |
| `tests/data/test_store.py` | Modify | Tests for new paths |
| `analytics/ledger.py` | Create | `Ledger` class — FIFO matching + equity curve |
| `tests/analytics/test_ledger.py` | Create | Ledger tests |
| `analytics/performance.py` | Create | `compute_performance` function |
| `tests/analytics/test_performance.py` | Create | Performance tests |
| `analytics/learnings.py` | Create | `LearningsStore` class |
| `tests/analytics/test_learnings.py` | Create | Learnings tests |
| `agent/dream.py` | Create | `DreamRunner` with validation |
| `tests/agent/test_dream.py` | Create | Dream tests |
| `engine/loop.py` | Modify | Add `dream_runner` param + `run_dream_if_due` method |
| `tests/engine/test_loop.py` | Modify | Tests for dream triggering |
| `agent/prompt.py` | Modify | Surface performance + learnings to trading agent |
| `tests/agent/test_prompt.py` | Modify | Test new prompt fields |
| `main.py` | Modify | Wire dream runner; call `run_dream_if_due` in outer loop |
| `pyproject.toml` | Modify | Add `analytics*` to packages.find.include |

---

### Task 1: Scaffolding + DataStore path additions

**Files:**
- Create: `analytics/__init__.py`
- Create: `tests/analytics/__init__.py`
- Modify: `pyproject.toml`
- Modify: `data/store.py`
- Modify: `tests/data/test_store.py`

- [ ] **Step 1: Create empty package files**

```bash
mkdir -p analytics tests/analytics
touch analytics/__init__.py tests/analytics/__init__.py
```

- [ ] **Step 2: Update pyproject.toml**

In `pyproject.toml`, find the `[tool.setuptools.packages.find]` block and update `include`:

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["connector*", "engine*", "data*", "agent*", "analytics*"]
```

- [ ] **Step 3: Write the failing tests for DataStore**

Append to `tests/data/test_store.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/data/test_store.py -v 2>&1 | tail -10`
Expected: FAIL — methods don't exist yet.

- [ ] **Step 5: Update `data/store.py`**

Add to the `ensure_dirs` method:

```python
    def ensure_dirs(self) -> None:
        for sub in ("quotes", "history", "options", "account", "log", "ledger", "learnings", "dreams"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
```

Append the following methods to the `DataStore` class (place them next to the existing path helpers):

```python
    def trades_path(self) -> Path:
        return self.root / "ledger" / "trades.jsonl"

    def equity_curve_path(self) -> Path:
        return self.root / "ledger" / "equity_curve.jsonl"

    def performance_path(self) -> Path:
        return self.root / "performance.json"

    def learnings_path(self) -> Path:
        return self.root / "learnings" / "learnings.jsonl"

    def dream_path(self, day: date) -> Path:
        return self.root / "dreams" / f"{day.isoformat()}.md"

    def last_dream_path(self) -> Path:
        return self.root / "last_dream.txt"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/data/test_store.py -v`
Expected: all tests pass (existing + 7 new).

- [ ] **Step 7: Verify pytest discovers the new analytics test dir**

Run: `pytest tests/ --collect-only -q 2>&1 | tail -5`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add analytics/__init__.py tests/analytics/__init__.py pyproject.toml data/store.py tests/data/test_store.py
git commit -m "chore: scaffold analytics package and add ledger/learnings/dream paths"
```

---

### Task 2: Ledger — FIFO trade matching + equity curve

**Files:**
- Create: `analytics/ledger.py`
- Create: `tests/analytics/test_ledger.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/analytics/test_ledger.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analytics/test_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analytics.ledger'`.

- [ ] **Step 3: Write the implementation**

Create `analytics/ledger.py`:

```python
import json
import re
from collections import deque
from datetime import date, datetime
from typing import Any

from connector.account import Account
from connector.orders import OrderStatus, Orders

from data.store import DataStore


def _is_option_symbol(code: str) -> bool:
    return bool(re.search(r"\d{6}[CP]", code))


def _parse_when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace(" ", "T"))


class Ledger:
    def __init__(self, store: DataStore) -> None:
        self._store = store

    async def rebuild(
        self, orders: Orders, account: Account, today: date,
    ) -> None:
        filled = await orders.get_orders(OrderStatus.FILLED)
        trades = self._compute_trades(filled)
        self._write_trades(trades)
        balance = await account.get_balance()
        self._update_equity_curve(today=today, balance=balance)

    def _compute_trades(self, filled_orders: list[dict]) -> list[dict]:
        # Sort all fills by time
        fills = sorted(
            filled_orders,
            key=lambda o: _parse_when(str(o["created_at"])),
        )
        # Per-symbol FIFO matching
        open_lots: dict[str, deque] = {}
        trades: list[dict] = []
        for fill in fills:
            symbol = fill["symbol"]
            side = str(fill["side"]).upper()
            qty = int(fill["filled_qty"]) if fill.get("filled_qty") else int(fill["qty"])
            price = float(fill.get("avg_fill_price") or fill["price"])
            when = _parse_when(str(fill["created_at"]))
            lots = open_lots.setdefault(symbol, deque())

            if side == "BUY":
                lots.append({"qty": qty, "price": price, "when": when})
            elif side == "SELL":
                remaining = qty
                while remaining > 0 and lots:
                    lot = lots[0]
                    matched = min(lot["qty"], remaining)
                    pnl = matched * (price - lot["price"])
                    holding = (when.date() - lot["when"].date()).days
                    trades.append({
                        "symbol": symbol,
                        "side": "long",
                        "qty": matched,
                        "entry_date": lot["when"].date().isoformat(),
                        "entry_price": lot["price"],
                        "exit_date": when.date().isoformat(),
                        "exit_price": price,
                        "pnl": pnl,
                        "holding_period_days": holding,
                        "is_option": _is_option_symbol(symbol),
                    })
                    lot["qty"] -= matched
                    remaining -= matched
                    if lot["qty"] == 0:
                        lots.popleft()
                # Remaining sell qty with no matching buy → ignored (short positions
                # not modeled in v1; would require separate tracking)
        return trades

    def _write_trades(self, trades: list[dict]) -> None:
        body = "\n".join(json.dumps(t, default=str) for t in trades)
        if body:
            body = body + "\n"
        self._store.atomic_write_text(self._store.trades_path(), body)

    def _update_equity_curve(self, today: date, balance: dict) -> None:
        path = self._store.equity_curve_path()
        existing: list[dict] = []
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    existing.append(json.loads(line))
        new_entry = {
            "date": today.isoformat(),
            "total_assets": float(balance["total_assets"]),
            "cash": float(balance["cash"]),
            "market_value": float(balance["market_value"]),
        }
        # Replace if same date already present
        existing = [e for e in existing if e["date"] != today.isoformat()]
        existing.append(new_entry)
        existing.sort(key=lambda e: e["date"])
        body = "\n".join(json.dumps(e) for e in existing) + "\n"
        self._store.atomic_write_text(path, body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analytics/test_ledger.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add analytics/ledger.py tests/analytics/test_ledger.py
git commit -m "feat: add Ledger with FIFO trade matching and equity curve"
```

---

### Task 3: Performance metrics

**Files:**
- Create: `analytics/performance.py`
- Create: `tests/analytics/test_performance.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/analytics/test_performance.py`:

```python
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
        # all_time + last_7d + today: 100
        {"symbol": "US.AAPL", "side": "long", "qty": 10,
         "entry_date": "2026-05-04", "entry_price": 150.0,
         "exit_date": "2026-05-04", "exit_price": 160.0,
         "pnl": 100.0, "holding_period_days": 0, "is_option": False},
        # all_time + last_7d only: -50
        {"symbol": "US.AAPL", "side": "long", "qty": 5,
         "entry_date": "2026-04-30", "entry_price": 150.0,
         "exit_date": "2026-05-01", "exit_price": 140.0,
         "pnl": -50.0, "holding_period_days": 1, "is_option": False},
        # all_time + last_30d only: 200
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
    # Equity goes up 100k → 110k → 95k → 105k. Max drawdown = (110 - 95)/110 = ~13.6%
    _write_equity(store, [
        {"date": "2026-04-15", "total_assets": 100000.0, "cash": 100000.0, "market_value": 0.0},
        {"date": "2026-04-20", "total_assets": 110000.0, "cash": 110000.0, "market_value": 0.0},
        {"date": "2026-04-25", "total_assets": 95000.0, "cash": 95000.0, "market_value": 0.0},
        {"date": "2026-05-04", "total_assets": 105000.0, "cash": 105000.0, "market_value": 0.0},
    ])
    account = _account_with_positions([])
    perf = await compute_performance(store=store, account=account, today=date(2026, 5, 4))
    # last_30_days covers all entries; max drawdown ≈ 13.6%
    assert perf["last_30_days"]["max_drawdown_pct"] == pytest.approx(13.6363636, rel=1e-3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analytics/test_performance.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `analytics/performance.py`:

```python
import json
from datetime import date, timedelta
from pathlib import Path

from connector.account import Account

from data.store import DataStore


async def compute_performance(
    store: DataStore, account: Account, today: date,
) -> dict:
    trades = _read_trades(store.trades_path())
    equity = _read_equity_curve(store.equity_curve_path())
    positions = await account.get_positions()
    unrealized = sum(float(p.get("unrealized_pl", 0.0)) for p in positions)

    today_str = today.isoformat()
    one_week = today - timedelta(days=7)
    one_month = today - timedelta(days=30)

    perf = {
        "as_of": today_str,
        "open_positions_unrealized_pnl": unrealized,
        "today": _summarize([t for t in trades if t["exit_date"] == today_str]),
        "last_7_days": _summarize_window(trades, equity, one_week, today),
        "last_30_days": _summarize_window(trades, equity, one_month, today),
        "all_time": _summarize_all_time(trades, equity),
        "by_symbol": _summarize_by_symbol(trades),
    }

    store.atomic_write_text(store.performance_path(), json.dumps(perf, indent=2))
    return perf


def _read_trades(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _read_equity_curve(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _summarize(window_trades: list[dict]) -> dict:
    if not window_trades:
        return {"realized_pnl": 0, "trades_closed": 0, "win_rate": 0,
                "avg_winner": 0, "avg_loser": 0}
    pnls = [float(t["pnl"]) for t in window_trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    return {
        "realized_pnl": sum(pnls),
        "trades_closed": len(window_trades),
        "win_rate": len(winners) / len(window_trades),
        "avg_winner": sum(winners) / len(winners) if winners else 0.0,
        "avg_loser": sum(losers) / len(losers) if losers else 0.0,
    }


def _summarize_window(
    trades: list[dict], equity: list[dict],
    start: date, end: date,
) -> dict:
    start_str = start.isoformat()
    end_str = end.isoformat()
    window_trades = [
        t for t in trades
        if start_str <= t["exit_date"] <= end_str
    ]
    summary = _summarize(window_trades)
    window_equity = [
        e for e in equity
        if start_str <= e["date"] <= end_str
    ]
    summary["max_drawdown_pct"] = _max_drawdown_pct(window_equity)
    return summary


def _summarize_all_time(trades: list[dict], equity: list[dict]) -> dict:
    summary = _summarize(trades)
    summary["max_drawdown_pct"] = _max_drawdown_pct(equity)
    summary["since"] = equity[0]["date"] if equity else None
    return summary


def _max_drawdown_pct(equity: list[dict]) -> float:
    if not equity:
        return 0.0
    peak = float(equity[0]["total_assets"])
    max_dd = 0.0
    for e in equity:
        v = float(e["total_assets"])
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _summarize_by_symbol(trades: list[dict]) -> dict:
    by_sym: dict[str, list[dict]] = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t)
    return {sym: _summarize(ts) for sym, ts in by_sym.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analytics/test_performance.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add analytics/performance.py tests/analytics/test_performance.py
git commit -m "feat: add compute_performance with windowed metrics and per-symbol breakdown"
```

---

### Task 4: LearningsStore

**Files:**
- Create: `analytics/learnings.py`
- Create: `tests/analytics/test_learnings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/analytics/test_learnings.py`:

```python
import json

import pytest

from analytics.learnings import LearningsStore
from data.store import DataStore


@pytest.fixture
def store(tmp_path):
    s = DataStore(tmp_path)
    s.ensure_dirs()
    return s


def test_read_active_returns_empty_when_no_file(store):
    ls = LearningsStore(store=store)
    assert ls.read_active() == []


def test_read_active_filters_inactive_entries(store):
    body = "\n".join(json.dumps(e) for e in [
        {"id": "1", "active": True, "observation": "a"},
        {"id": "2", "active": False, "observation": "b"},
        {"id": "3", "active": True, "observation": "c"},
    ]) + "\n"
    store.atomic_write_text(store.learnings_path(), body)
    ls = LearningsStore(store=store)
    actives = ls.read_active()
    assert [e["id"] for e in actives] == ["1", "3"]


def test_write_replaces_full_file(store):
    body = json.dumps({"id": "old", "active": True, "observation": "old"}) + "\n"
    store.atomic_write_text(store.learnings_path(), body)
    ls = LearningsStore(store=store)
    ls.write([
        {"id": "new1", "active": True, "observation": "x"},
        {"id": "new2", "active": False, "observation": "y"},
    ])
    lines = store.learnings_path().read_text().splitlines()
    ids = [json.loads(l)["id"] for l in lines]
    assert ids == ["new1", "new2"]


def test_write_empty_list_produces_empty_file(store):
    ls = LearningsStore(store=store)
    ls.write([])
    assert store.learnings_path().read_text() == ""


def test_read_all_returns_all_entries_including_inactive(store):
    body = "\n".join(json.dumps(e) for e in [
        {"id": "1", "active": True, "observation": "a"},
        {"id": "2", "active": False, "observation": "b"},
    ]) + "\n"
    store.atomic_write_text(store.learnings_path(), body)
    ls = LearningsStore(store=store)
    assert len(ls.read_all()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/analytics/test_learnings.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `analytics/learnings.py`:

```python
import json

from data.store import DataStore


class LearningsStore:
    def __init__(self, store: DataStore) -> None:
        self._store = store

    def read_all(self) -> list[dict]:
        path = self._store.learnings_path()
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def read_active(self) -> list[dict]:
        return [e for e in self.read_all() if e.get("active") is True]

    def write(self, entries: list[dict]) -> None:
        if not entries:
            self._store.atomic_write_text(self._store.learnings_path(), "")
            return
        body = "\n".join(json.dumps(e, default=str) for e in entries) + "\n"
        self._store.atomic_write_text(self._store.learnings_path(), body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analytics/test_learnings.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add analytics/learnings.py tests/analytics/test_learnings.py
git commit -m "feat: add LearningsStore for structured persistent observations"
```

---

### Task 5: DreamRunner

**Files:**
- Create: `agent/dream.py`
- Create: `tests/agent/test_dream.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_dream.py`:

```python
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
    # Pre-create a valid learnings file so validation passes (subprocess writes
    # to it; in this mock, the runner does nothing — so we pre-seed it)
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
    # last_dream not updated
    assert not store.last_dream_path().exists()


async def test_run_rejects_missing_learnings_file(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps
    # Don't pre-seed learnings — subprocess "succeeded" but left no file
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
    # Pre-existing has 10 entries
    prior = "\n".join(
        json.dumps({"id": f"l{i}", "created_at": "2026-05-03T08:00",
                    "category": "general", "observation": "x", "evidence": "x",
                    "active": True})
        for i in range(10)
    ) + "\n"
    store.atomic_write_text(store.learnings_path(), prior)

    # The dream subprocess "writes" only 3 entries — but our runner mock doesn't
    # actually run claude. Simulate by having the runner mock write the file:
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
    # Prior file should be restored
    lines = store.learnings_path().read_text().splitlines()
    assert len(lines) == 10
    log_events = [c.args[0]["event"] for c in log_writer.write.call_args_list]
    assert "dream_validation_failed" in log_events


async def test_run_rejects_entries_missing_required_fields(deps):
    ledger, performance_fn, runner, log_writer, account, orders, store = deps

    def write_invalid(*_args, **_kwargs):
        # Missing 'evidence' field
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent/test_dream.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `agent/dream.py`:

```python
import json
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from connector.account import Account
from connector.orders import Orders

from agent.runner import AgentResult, AgentRunner
from analytics.ledger import Ledger
from data.store import DataStore


_REQUIRED_LEARNING_FIELDS = {
    "id", "created_at", "category", "observation", "evidence", "active",
}


_DREAM_PROMPT = """You are reflecting on the autonomous trading agent's recent
activity. Your role is REFLECTIVE ANALYST, not trader. You will not place trades.

Your goal: identify patterns in the past data and update the agent's persistent
learnings file with new observations or refinements.

REQUIRED DISCIPLINE:
- Sample size: every observation must cite the trade count it's based on.
  Do not propose strategy changes based on fewer than 20 trades unless the
  pattern is overwhelming (e.g., 5 of 5).
- Provenance: every entry must include `evidence` (numbers, not vibes).
- Supersession: when refining or retiring an existing learning, mark the old
  entry `active: false` and add a new entry with `supersedes: <old_id>` rather
  than silently editing.

Inputs you may read:
- {trades_path} — closed trades (one JSON object per line)
- {equity_path} — daily account snapshots
- {performance_path} — pre-computed metrics
- {learnings_path} — current persistent learnings (JSONL)
- {decisions_dir}/decisions-YYYY-MM-DD.jsonl — past decision logs

You have full Claude Code tool access: read files, write Python scripts to
analyze them, run them, and observe results.

Outputs you must produce:
1. Write a markdown reflection to {dream_path} summarizing what you observed
   and what you decided to change. At least 200 characters.
2. Write the updated learnings to {learnings_path} as JSONL. Each entry must
   include the fields: id, created_at, category, observation, evidence, active.
   Optional fields: dream_id, confidence, supersedes.

Begin reflecting now. When done, exit cleanly."""


class DreamRunner:
    def __init__(
        self,
        ledger: Ledger,
        performance_fn: Callable[..., Awaitable[dict]],
        runner: AgentRunner,
        store: DataStore,
        log_writer,
        account: Account,
        orders: Orders,
    ) -> None:
        self._ledger = ledger
        self._performance_fn = performance_fn
        self._runner = runner
        self._store = store
        self._log_writer = log_writer
        self._account = account
        self._orders = orders

    async def run(self, now: datetime) -> bool:
        today = now.date()
        try:
            await self._ledger.rebuild(orders=self._orders, account=self._account, today=today)
            await self._performance_fn(store=self._store, account=self._account, today=today)
        except Exception as exc:
            self._log_writer.write({
                "event": "dream_failed",
                "time": now.isoformat(),
                "phase": "data_refresh",
                "error": repr(exc),
            })
            return False

        prior_learnings = self._snapshot_learnings()

        prompt = self._build_prompt(today)
        result: AgentResult = await self._runner.run(prompt)

        if result.exit_code != 0 or result.timed_out:
            self._log_writer.write({
                "event": "dream_failed",
                "time": now.isoformat(),
                "phase": "subprocess",
                "exit_code": result.exit_code,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
            })
            return False

        if not self._validate_outputs(prior_learnings, today):
            # Restore prior learnings if they were overwritten
            if prior_learnings is not None:
                self._store.atomic_write_text(self._store.learnings_path(), prior_learnings)
            self._log_writer.write({
                "event": "dream_validation_failed",
                "time": now.isoformat(),
            })
            return False

        self._store.atomic_write_text(self._store.last_dream_path(), today.isoformat() + "\n")
        self._log_writer.write({
            "event": "dream_completed",
            "time": now.isoformat(),
            "duration_seconds": result.duration_seconds,
        })
        return True

    def _snapshot_learnings(self) -> str | None:
        path = self._store.learnings_path()
        if not path.exists():
            return None
        return path.read_text()

    def _build_prompt(self, today) -> str:
        return _DREAM_PROMPT.format(
            trades_path=self._store.trades_path(),
            equity_path=self._store.equity_curve_path(),
            performance_path=self._store.performance_path(),
            learnings_path=self._store.learnings_path(),
            decisions_dir=self._store.root / "log",
            dream_path=self._store.dream_path(today),
        )

    def _validate_outputs(self, prior_learnings: str | None, today) -> bool:
        learnings_path = self._store.learnings_path()
        if not learnings_path.exists():
            return False
        try:
            new_entries = [
                json.loads(line) for line in learnings_path.read_text().splitlines()
                if line.strip()
            ]
        except json.JSONDecodeError:
            return False

        # Required fields check
        for entry in new_entries:
            if not _REQUIRED_LEARNING_FIELDS.issubset(entry.keys()):
                return False

        # Shrinkage check
        if prior_learnings:
            prior_count = len([
                line for line in prior_learnings.splitlines() if line.strip()
            ])
            if prior_count > 0 and len(new_entries) < prior_count * 0.5:
                return False

        # Dream markdown check (warn-only — don't fail validation if missing,
        # but do log; we still return True). Empty/missing dream is acceptable.
        dream_path = self._store.dream_path(today)
        if dream_path.exists() and len(dream_path.read_text()) < 200:
            self._log_writer.write({
                "event": "dream_markdown_short",
                "time": today.isoformat(),
                "size": len(dream_path.read_text()),
            })

        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent/test_dream.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/dream.py tests/agent/test_dream.py
git commit -m "feat: add DreamRunner for daily reflection cycle with output validation"
```

---

### Task 6: Engine triggers dream once per day

**Files:**
- Modify: `engine/loop.py`
- Modify: `tests/engine/test_loop.py`

- [ ] **Step 1: Update test fixtures + add new tests**

In `tests/engine/test_loop.py`, locate the `deps` fixture and add a `dream_runner` mock. The fixture currently returns a 9-tuple; extend to 10:

```python
    dream_runner = MagicMock()
    dream_runner.run = AsyncMock(return_value=True)
    return (collector, runner, prompt_builder, account, orders,
            fill_buffer, order_update_buffer, executor, store, dream_runner)
```

Also configure `store` to support last_dream_path:
```python
    store.last_dream_path = MagicMock(return_value=Path("/tmp/last_dream.txt"))
```

Update every test that unpacks `deps` to include `dream_runner` as the new last element. Update every `Engine(...)` constructor call to add `dream_runner=dream_runner,` as a kwarg.

Append two new tests:

```python
async def test_run_dream_if_due_calls_when_no_prior_dream(deps, calendar, tmp_path):
    (collector, runner, prompt_builder, account, orders,
     fill_buffer, order_update_buffer, executor, store, dream_runner) = deps
    store.last_dream_path = MagicMock(return_value=tmp_path / "last_dream.txt")
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=store, calendar=calendar,
        dream_runner=dream_runner, log_writer=MagicMock(),
    )
    await engine.run_dream_if_due(now=datetime(2026, 5, 4, 8, 0, tzinfo=ZoneInfo("America/New_York")))
    dream_runner.run.assert_awaited_once()


async def test_run_dream_if_due_skips_when_already_dreamed_today(deps, calendar, tmp_path):
    (collector, runner, prompt_builder, account, orders,
     fill_buffer, order_update_buffer, executor, store, dream_runner) = deps
    last_dream_file = tmp_path / "last_dream.txt"
    last_dream_file.write_text("2026-05-04\n")
    store.last_dream_path = MagicMock(return_value=last_dream_file)
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=store, calendar=calendar,
        dream_runner=dream_runner, log_writer=MagicMock(),
    )
    await engine.run_dream_if_due(now=datetime(2026, 5, 4, 8, 0, tzinfo=ZoneInfo("America/New_York")))
    dream_runner.run.assert_not_awaited()


async def test_run_dream_if_due_swallows_dream_failure(deps, calendar, tmp_path):
    (collector, runner, prompt_builder, account, orders,
     fill_buffer, order_update_buffer, executor, store, dream_runner) = deps
    dream_runner.run = AsyncMock(return_value=False)
    store.last_dream_path = MagicMock(return_value=tmp_path / "last_dream.txt")
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=store, calendar=calendar,
        dream_runner=dream_runner, log_writer=MagicMock(),
    )
    # Should not raise
    await engine.run_dream_if_due(now=datetime(2026, 5, 4, 8, 0, tzinfo=ZoneInfo("America/New_York")))
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `pytest tests/engine/test_loop.py -v 2>&1 | tail -10`
Expected: FAIL — Engine doesn't accept `dream_runner` parameter, doesn't have `run_dream_if_due` method.

- [ ] **Step 3: Update Engine**

In `engine/loop.py`:

1. Add to imports:
```python
from agent.dream import DreamRunner
```

2. Add `dream_runner: DreamRunner` to `Engine.__init__` signature, immediately before `log_writer`. Store: `self._dream_runner = dream_runner`.

3. Append a new method to the `Engine` class:

```python
    async def run_dream_if_due(self, now: datetime) -> None:
        today_str = now.date().isoformat()
        last_path = self._store.last_dream_path()
        if last_path.exists() and last_path.read_text().strip() == today_str:
            return
        try:
            await self._dream_runner.run(now=now)
        except Exception:
            # Dream failures must never halt trading
            pass
```

- [ ] **Step 4: Run all engine tests**

Run: `pytest tests/engine/test_loop.py -v`
Expected: all tests pass (previous count + 3 new).

- [ ] **Step 5: Commit**

```bash
git add engine/loop.py tests/engine/test_loop.py
git commit -m "feat: Engine triggers dream once per day via run_dream_if_due"
```

---

### Task 7: PromptBuilder surfaces performance and learnings

**Files:**
- Modify: `agent/prompt.py`
- Modify: `tests/agent/test_prompt.py`

- [ ] **Step 1: Add the new failing test**

Append to `tests/agent/test_prompt.py`:

```python
def test_prompt_includes_performance_and_learnings_paths(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"], history_interval="1m")
    prompt = builder.build(
        now=datetime(2026, 5, 4, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[],
        recent_fills=[], recent_order_updates=[],
        daily_pnl=0.0,
    )
    assert str(store.performance_path()) in prompt
    assert str(store.learnings_path()) in prompt
    assert "performance" in prompt.lower()
    assert "learnings" in prompt.lower()
```

- [ ] **Step 2: Run new test to verify it fails**

Run: `pytest tests/agent/test_prompt.py::test_prompt_includes_performance_and_learnings_paths -v`
Expected: FAIL.

- [ ] **Step 3: Update PromptBuilder**

In `agent/prompt.py`:

In the `files` dict construction inside `build()`, add (after the existing `recent_order_updates` entry):

```python
            "performance": str(self._store.performance_path()),
            "learnings": str(self._store.learnings_path()),
```

In `_SYSTEM_PROMPT`, add a new paragraph near the end (after the existing observability bullets, before the "Important" closing notes):

```
Past performance and your accumulated learnings:
- performance.json — your track record across windows (today, last 7 / 30 days,
  all-time, per-symbol breakdown), plus open-position unrealized P&L.
- learnings/learnings.jsonl — observations from your prior reflections. Active
  entries (active=true) represent your current beliefs about what works and
  what doesn't. Consult both before sizing positions and choosing trades.
```

- [ ] **Step 4: Run all prompt tests**

Run: `pytest tests/agent/test_prompt.py -v`
Expected: all tests pass (previous count + 1 new).

- [ ] **Step 5: Commit**

```bash
git add agent/prompt.py tests/agent/test_prompt.py
git commit -m "feat: PromptBuilder surfaces performance and learnings to trading agent"
```

---

### Task 8: main.py wiring + final integration check

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update main.py**

Open `main.py`. Add to imports:

```python
from agent.dream import DreamRunner
from analytics.ledger import Ledger
from analytics.performance import compute_performance
```

After `runner = AgentRunner(timeout_seconds=config.claude_timeout_seconds)` is constructed (or near the other component constructions), add:

```python
        ledger = Ledger(store=store)
        dream_runner = DreamRunner(
            ledger=ledger, performance_fn=compute_performance,
            runner=runner, store=store, log_writer=log_writer,
            account=account, orders=orders,
        )
```

Place this after `log_writer = JsonlLogWriter(store)` is constructed so `log_writer` is in scope.

In the `Engine(...)` constructor call, add `dream_runner=dream_runner,` as a kwarg.

In the outer wait loop, locate the section that runs after the market-closed branch and before `await engine.tick(now=now)`. Add a dream call just before the tick:

```python
            await engine.run_dream_if_due(now=now)
            await engine.tick(now=now)
```

- [ ] **Step 2: Verify imports resolve cleanly**

Run:
```bash
python3 -c "
from analytics.ledger import Ledger
from analytics.performance import compute_performance
from analytics.learnings import LearningsStore
from agent.dream import DreamRunner
from engine.loop import Engine
from data.store import DataStore
print('All imports OK')
"
```
Expected: `All imports OK`.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: all tests pass (previous 136 + ~32 new ≈ 168), no warnings.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "chore: wire DreamRunner and analytics through main"
```
