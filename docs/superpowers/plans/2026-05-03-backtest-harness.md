# Backtest Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backtest harness that runs the existing autonomous trading agent against historical market data, with bar-aware order matching, configurable cadences, and an optional promotion path that copies backtest-derived learnings into the live system.

**Architecture:** A new `backtest/` package implements the connector's `MarketData` / `Account` / `Orders` interfaces from cached historical bars + synthetic state, plus a `SimulatedClock` and a `BacktestRunner` that drives the existing Engine through a date range. The Engine, agent, dream, and analytics code is reused unchanged.

**Tech Stack:** Python 3.11+, moomoo-api (for cache backfills), pandas (already used), pytest, pytest-asyncio. The `claude` CLI must be installed for end-to-end runs.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backtest/__init__.py` | Create | Package marker |
| `backtest/__main__.py` | Create | Delegates to `cli.main` |
| `tests/backtest/__init__.py` | Create | Test package marker |
| `pyproject.toml` | Modify | Add `backtest*` to packages.find.include |
| `backtest/clock.py` | Create | `SimulatedClock` |
| `tests/backtest/test_clock.py` | Create | Clock tests |
| `backtest/cache.py` | Create | `HistoricalDataCache` (JSONL-backed) |
| `tests/backtest/test_cache.py` | Create | Cache tests |
| `backtest/matcher.py` | Create | `OrderMatcher` — bar-aware fills |
| `tests/backtest/test_matcher.py` | Create | Matcher tests |
| `backtest/broker.py` | Create | `BacktestBroker` composing 3 interfaces |
| `tests/backtest/test_broker.py` | Create | Broker tests |
| `backtest/runner.py` | Create | `BacktestRunner` replay loop |
| `tests/backtest/test_runner.py` | Create | Runner tests |
| `backtest/promote.py` | Create | `promote_learnings` function |
| `tests/backtest/test_promote.py` | Create | Promotion tests |
| `backtest/cli.py` | Create | argparse entry point |
| `agent/prompt.py` | Modify | Add backtest-source learnings note |

---

### Task 1: Scaffolding + DataStore.history_cache_dir

**Files:**
- Create: `backtest/__init__.py`, `tests/backtest/__init__.py`
- Modify: `pyproject.toml`, `data/store.py`, `tests/data/test_store.py`

- [ ] **Step 1: Create empty package files**

```bash
mkdir -p backtest tests/backtest
touch backtest/__init__.py tests/backtest/__init__.py
```

- [ ] **Step 2: Update pyproject.toml**

In `pyproject.toml`, locate `[tool.setuptools.packages.find]` and update `include`:

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["connector*", "engine*", "data*", "agent*", "analytics*", "backtest*"]
```

- [ ] **Step 3: Write the failing tests**

Append to `tests/data/test_store.py`:

```python
def test_history_cache_dir(tmp_path):
    store = DataStore(tmp_path)
    assert store.history_cache_dir() == tmp_path / "historical_cache"


def test_backtest_run_dir(tmp_path):
    store = DataStore(tmp_path)
    assert store.backtest_run_dir("2026-05-04T22-15-00_label") == (
        tmp_path / "backtests" / "2026-05-04T22-15-00_label"
    )
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/data/test_store.py::test_history_cache_dir tests/data/test_store.py::test_backtest_run_dir -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 5: Add the implementation**

In `data/store.py`, append to the `DataStore` class:

```python
    def history_cache_dir(self) -> Path:
        return self.root / "historical_cache"

    def backtest_run_dir(self, run_id: str) -> Path:
        return self.root / "backtests" / run_id
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/data/test_store.py -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backtest/__init__.py tests/backtest/__init__.py pyproject.toml data/store.py tests/data/test_store.py
git commit -m "chore: scaffold backtest package and add cache + run directory paths"
```

---

### Task 2: SimulatedClock

**Files:**
- Create: `backtest/clock.py`
- Create: `tests/backtest/test_clock.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/backtest/test_clock.py`:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backtest.clock import SimulatedClock


def test_clock_returns_initial_now():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    assert clock.now() == start


def test_clock_advance_moves_now_forward():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == start + timedelta(minutes=5)


def test_clock_advance_is_cumulative():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    clock.advance(timedelta(minutes=5))
    clock.advance(timedelta(minutes=10))
    assert clock.now() == start + timedelta(minutes=15)


def test_clock_set_replaces_current_time():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    new_time = datetime(2026, 2, 1, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    clock.set(new_time)
    assert clock.now() == new_time
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backtest/test_clock.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `backtest/clock.py`:

```python
from datetime import datetime, timedelta


class SimulatedClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set(self, new_time: datetime) -> None:
        self._now = new_time
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backtest/test_clock.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backtest/clock.py tests/backtest/test_clock.py
git commit -m "feat: add SimulatedClock for backtest time control"
```

---

### Task 3: HistoricalDataCache

**Files:**
- Create: `backtest/cache.py`
- Create: `tests/backtest/test_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/backtest/test_cache.py`:

```python
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backtest.cache import HistoricalDataCache


def _market_data_with_history(rows):
    md = MagicMock()
    md.get_price_history = AsyncMock(return_value=rows)
    return md


async def test_ensure_range_fetches_when_cache_empty(tmp_path):
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))
    md.get_price_history.assert_awaited_once()
    cache_file = tmp_path / "AAPL_1m.jsonl"
    assert cache_file.exists()
    line = json.loads(cache_file.read_text().strip())
    assert line["open"] == 100.0


async def test_ensure_range_idempotent_when_already_cached(tmp_path):
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))
    md.get_price_history.reset_mock()
    # second call should not refetch
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))
    md.get_price_history.assert_not_awaited()


async def test_ensure_range_fetches_extension(tmp_path):
    # Pre-existing cache for jan 15
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))

    # Now extend with jan 16
    md.get_price_history = AsyncMock(return_value=[
        {"time": "2026-01-16 09:30:00", "open": 102.0, "close": 103.0,
         "high": 103.5, "low": 101.5, "volume": 1500, "turnover": 154500.0},
    ])
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 16), end=date(2026, 1, 16))

    lines = (tmp_path / "AAPL_1m.jsonl").read_text().splitlines()
    assert len(lines) == 2


async def test_load_bars_returns_dataframe(tmp_path):
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
        {"time": "2026-01-16 09:30:00", "open": 102.0, "close": 103.0,
         "high": 103.5, "low": 101.5, "volume": 1500, "turnover": 154500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 16))

    df = cache.load_bars("AAPL", "1m", date(2026, 1, 15), date(2026, 1, 16))
    assert len(df) == 2
    assert df.iloc[0]["open"] == 100.0


def test_load_bars_raises_when_cache_missing(tmp_path):
    cache = HistoricalDataCache(cache_dir=tmp_path)
    with pytest.raises(ValueError, match="not in cache"):
        cache.load_bars("AAPL", "1m", date(2026, 1, 15), date(2026, 1, 15))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backtest/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `backtest/cache.py`:

```python
import json
from datetime import date
from pathlib import Path

import moomoo as ft
import pandas as pd

from connector.market_data import MarketData


_INTERVAL_TO_KTYPE = {
    "1m": ft.KLType.K_1M,
    "5m": ft.KLType.K_5M,
    "15m": ft.KLType.K_15M,
    "1h": ft.KLType.K_60M,
    "1d": ft.KLType.K_DAY,
}


class HistoricalDataCache:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def ensure_range(
        self, market_data: MarketData, symbol: str, interval: str,
        start: date, end: date,
    ) -> None:
        existing_dates = self._cached_dates(symbol, interval)
        requested_dates = self._all_dates(start, end)
        missing = sorted(requested_dates - existing_dates)
        if not missing:
            return
        ktype = _INTERVAL_TO_KTYPE[interval]
        rows = await market_data.get_price_history(
            symbol, missing[0], missing[-1], ktype,
        )
        self._append_rows(symbol, interval, rows)

    def load_bars(
        self, symbol: str, interval: str, start: date, end: date,
    ) -> pd.DataFrame:
        cache_file = self._cache_path(symbol, interval)
        if not cache_file.exists():
            raise ValueError(f"{symbol} {interval} not in cache")
        rows = [json.loads(line) for line in cache_file.read_text().splitlines() if line.strip()]
        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError(f"{symbol} {interval} not in cache")
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time").reset_index(drop=True)
        mask = (df["time"].dt.date >= start) & (df["time"].dt.date <= end)
        return df.loc[mask].reset_index(drop=True)

    def _cache_path(self, symbol: str, interval: str) -> Path:
        return self._cache_dir / f"{symbol}_{interval}.jsonl"

    def _cached_dates(self, symbol: str, interval: str) -> set[date]:
        cache_file = self._cache_path(symbol, interval)
        if not cache_file.exists():
            return set()
        result: set[date] = set()
        for line in cache_file.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            result.add(date.fromisoformat(str(row["time"])[:10]))
        return result

    @staticmethod
    def _all_dates(start: date, end: date) -> set[date]:
        from datetime import timedelta
        out = set()
        d = start
        while d <= end:
            out.add(d)
            d = d + timedelta(days=1)
        return out

    def _append_rows(self, symbol: str, interval: str, rows: list[dict]) -> None:
        cache_file = self._cache_path(symbol, interval)
        existing = ""
        if cache_file.exists():
            existing = cache_file.read_text()
        with cache_file.open("w") as f:
            if existing:
                f.write(existing)
                if not existing.endswith("\n"):
                    f.write("\n")
            for row in rows:
                f.write(json.dumps(row, default=str) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backtest/test_cache.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backtest/cache.py tests/backtest/test_cache.py
git commit -m "feat: add HistoricalDataCache backed by JSONL"
```

---

### Task 4: OrderMatcher

**Files:**
- Create: `backtest/matcher.py`
- Create: `tests/backtest/test_matcher.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/backtest/test_matcher.py`:

```python
from datetime import datetime

import pytest

from backtest.matcher import OrderMatcher, PendingOrder


def _bar(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close,
            "volume": 1000, "time": datetime(2026, 1, 15, 9, 31)}


def test_limit_buy_fills_when_bar_low_crosses():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                         qty=10, order_type="LIMIT", limit_price=100.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 102, 99.5, 100.5))
    assert len(fills) == 1
    assert fills[0]["price"] == 100.0
    assert fills[0]["qty"] == 10


def test_limit_buy_does_not_fill_when_bar_low_above_limit():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                         qty=10, order_type="LIMIT", limit_price=100.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 102, 100.5, 101.5))
    assert fills == []


def test_limit_sell_fills_when_bar_high_crosses():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="SELL",
                         qty=10, order_type="LIMIT", limit_price=105.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 105.5, 100, 102))
    assert fills[0]["price"] == 105.0


def test_limit_sell_does_not_fill_when_bar_high_below_limit():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="SELL",
                         qty=10, order_type="LIMIT", limit_price=105.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 104, 100, 102))
    assert fills == []


def test_market_buy_fills_at_bar_open():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                         qty=5, order_type="MARKET", limit_price=None)
    fills = matcher.process_bar(orders=[order], bar=_bar(101.25, 102, 100, 101.5))
    assert fills[0]["price"] == 101.25
    assert fills[0]["qty"] == 5


def test_market_sell_fills_at_bar_open():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="SELL",
                         qty=5, order_type="MARKET", limit_price=None)
    fills = matcher.process_bar(orders=[order], bar=_bar(101.25, 102, 100, 101.5))
    assert fills[0]["price"] == 101.25


def test_multiple_orders_processed_independently():
    matcher = OrderMatcher()
    o1 = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                      qty=10, order_type="LIMIT", limit_price=99.0)  # won't fill
    o2 = PendingOrder(order_id="O2", symbol="AAPL", side="BUY",
                      qty=5, order_type="LIMIT", limit_price=100.5)  # will fill
    fills = matcher.process_bar(orders=[o1, o2], bar=_bar(101, 102, 100, 101.5))
    assert len(fills) == 1
    assert fills[0]["order_id"] == "O2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backtest/test_matcher.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `backtest/matcher.py`:

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class PendingOrder:
    order_id: str
    symbol: str
    side: str          # "BUY" or "SELL"
    qty: int
    order_type: str    # "LIMIT" or "MARKET"
    limit_price: Optional[float]


class OrderMatcher:
    def process_bar(
        self, orders: list[PendingOrder], bar: dict,
    ) -> list[dict]:
        """Returns a list of fill dicts for orders that the bar's range
        crossed. Caller is responsible for removing filled orders from
        their pending list."""
        fills: list[dict] = []
        for order in orders:
            fill = self._try_fill(order, bar)
            if fill is not None:
                fills.append(fill)
        return fills

    def _try_fill(self, order: PendingOrder, bar: dict) -> Optional[dict]:
        if order.order_type == "MARKET":
            price = float(bar["open"])
            return {
                "order_id": order.order_id, "symbol": order.symbol,
                "side": order.side, "qty": order.qty, "price": price,
                "filled_at": str(bar["time"]),
            }
        if order.order_type == "LIMIT":
            limit = float(order.limit_price)
            if order.side == "BUY" and float(bar["low"]) <= limit:
                return {
                    "order_id": order.order_id, "symbol": order.symbol,
                    "side": order.side, "qty": order.qty, "price": limit,
                    "filled_at": str(bar["time"]),
                }
            if order.side == "SELL" and float(bar["high"]) >= limit:
                return {
                    "order_id": order.order_id, "symbol": order.symbol,
                    "side": order.side, "qty": order.qty, "price": limit,
                    "filled_at": str(bar["time"]),
                }
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backtest/test_matcher.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backtest/matcher.py tests/backtest/test_matcher.py
git commit -m "feat: add OrderMatcher for bar-aware backtest fills"
```

---

### Task 5: BacktestBroker

**Files:**
- Create: `backtest/broker.py`
- Create: `tests/backtest/test_broker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/backtest/test_broker.py`:

```python
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
    assert quote["last_price"] == 99.0  # close of 9:31 bar


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
    # advance clock so latest bar is the 9:31 bar (low 98.5, crosses limit 100)
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
    assert bal["cash"] == 100000.0 - 1000.0  # 10 shares @ $100
    # market_value = 10 * 99.0 (current quote) = 990
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backtest/test_broker.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `backtest/broker.py`:

```python
import itertools
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Optional

from connector.exceptions import MoomooMarketDataError, MoomooOrderError
from connector.orders import OrderSpec, OrderStatus

from backtest.cache import HistoricalDataCache
from backtest.clock import SimulatedClock
from backtest.matcher import OrderMatcher, PendingOrder


class BacktestBroker:
    def __init__(
        self, cache: HistoricalDataCache, clock: SimulatedClock,
        watchlist: list[str], interval: str, starting_cash: float,
    ) -> None:
        self._cache = cache
        self._clock = clock
        self._watchlist = watchlist
        self._interval = interval
        self._cash = starting_cash
        self._positions: dict[str, dict] = {}
        self._pending: list[PendingOrder] = []
        self._filled: list[dict] = []
        self._fill_callbacks: list[Callable[[dict], None]] = []
        self._order_update_callbacks: list[Callable[[dict], None]] = []
        self._matcher = OrderMatcher()
        self._id_counter = itertools.count(1)

        self._market_data = _BacktestMarketData(self)
        self._account = _BacktestAccount(self)
        self._orders = _BacktestOrders(self)

    @property
    def market_data(self) -> "_BacktestMarketData": return self._market_data

    @property
    def account(self) -> "_BacktestAccount": return self._account

    @property
    def orders(self) -> "_BacktestOrders": return self._orders

    def process_bar(self, bar_time: datetime) -> None:
        if not self._pending:
            return
        bar = self._latest_bar_for_each_symbol()
        per_symbol_bars = bar
        # group pending by symbol so we match each against its latest bar
        remaining: list[PendingOrder] = []
        for order in self._pending:
            sym_bar = per_symbol_bars.get(order.symbol)
            if sym_bar is None:
                remaining.append(order)
                continue
            fills = self._matcher.process_bar(orders=[order], bar=sym_bar)
            if not fills:
                remaining.append(order)
                continue
            fill = fills[0]
            self._apply_fill(order, fill)
        self._pending = remaining

    def _latest_bar_for_each_symbol(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        now = self._clock.now()
        for sym in self._watchlist:
            df = self._cache.load_bars(
                sym, self._interval,
                now.date() - timedelta(days=1), now.date(),
            )
            if df.empty:
                continue
            df = df[df["time"] <= now.replace(tzinfo=None)]
            if df.empty:
                continue
            row = df.iloc[-1]
            out[sym] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "time": row["time"],
            }
        return out

    def _apply_fill(self, order: PendingOrder, fill: dict) -> None:
        cost = fill["qty"] * fill["price"]
        if order.side == "BUY":
            self._cash -= cost
            pos = self._positions.setdefault(order.symbol, {
                "symbol": order.symbol, "qty": 0, "cost_price": 0.0,
                "current_price": fill["price"], "market_value": 0.0,
                "unrealized_pl": 0.0, "is_option": False,
                "name": order.symbol, "currency": "USD", "side": "LONG",
            })
            old_qty = pos["qty"]
            old_cost = pos["cost_price"]
            new_qty = old_qty + fill["qty"]
            pos["cost_price"] = (
                (old_qty * old_cost + cost) / new_qty if new_qty > 0 else 0.0
            )
            pos["qty"] = new_qty
        else:  # SELL
            self._cash += cost
            pos = self._positions.get(order.symbol)
            if pos is not None:
                pos["qty"] -= fill["qty"]
                if pos["qty"] <= 0:
                    del self._positions[order.symbol]

        filled_record = {
            "order_id": order.order_id, "symbol": order.symbol,
            "name": order.symbol, "side": order.side,
            "order_type": order.order_type, "price": fill["price"],
            "qty": order.qty, "filled_qty": fill["qty"],
            "avg_fill_price": fill["price"],
            "status": OrderStatus.FILLED, "created_at": fill["filled_at"],
        }
        self._filled.append(filled_record)
        for cb in self._fill_callbacks:
            try: cb(fill)
            except Exception: pass
        for cb in self._order_update_callbacks:
            try:
                cb({
                    "order_id": order.order_id, "symbol": order.symbol,
                    "side": order.side, "qty": order.qty,
                    "price": fill["price"], "filled_qty": fill["qty"],
                    "order_status": "FILLED_ALL", "updated_at": fill["filled_at"],
                })
            except Exception: pass

    def _next_order_id(self) -> str:
        return f"BT-{next(self._id_counter):06d}"


class _BacktestMarketData:
    def __init__(self, broker: BacktestBroker) -> None:
        self._broker = broker

    async def get_quote(self, symbol: str) -> dict:
        bar = self._broker._latest_bar_for_each_symbol().get(symbol)
        if bar is None:
            raise MoomooMarketDataError(f"no bar for {symbol}")
        return {
            "symbol": symbol,
            "last_price": float(bar["close"]),
            "open_price": float(bar["open"]),
            "high_price": float(bar["high"]),
            "low_price": float(bar["low"]),
            "volume": int(bar["volume"]),
            "bid_price": float(bar["close"]) - 0.01,
            "ask_price": float(bar["close"]) + 0.01,
        }

    async def get_price_history(self, symbol, start, end, interval):
        from datetime import timedelta
        # ignore SDK ktype, use the cache's interval
        df = self._broker._cache.load_bars(
            symbol, self._broker._interval, start, end,
        )
        return [
            {"time": str(row["time"]), "open": float(row["open"]),
             "close": float(row["close"]), "high": float(row["high"]),
             "low": float(row["low"]), "volume": int(row["volume"]),
             "turnover": float(row.get("turnover", 0.0))}
            for _, row in df.iterrows()
        ]

    async def get_option_chain(self, symbol, expiry):
        raise MoomooMarketDataError("backtest mode: options not supported")

    async def subscribe_quotes(self, symbol, callback) -> None:
        return None

    async def get_trading_days(self, market: str, start, end) -> list[dict]:
        # Aggregate trading days across all watchlist symbols
        all_dates: set[date] = set()
        for sym in self._broker._watchlist:
            try:
                df = self._broker._cache.load_bars(
                    sym, self._broker._interval, start, end,
                )
            except ValueError:
                continue
            for _, row in df.iterrows():
                all_dates.add(row["time"].date() if hasattr(row["time"], "date") else date.fromisoformat(str(row["time"])[:10]))
        return [{"date": d, "type": "WHOLE"} for d in sorted(all_dates)]


class _BacktestAccount:
    def __init__(self, broker: BacktestBroker) -> None:
        self._broker = broker

    async def get_positions(self) -> list[dict]:
        bars = self._broker._latest_bar_for_each_symbol()
        out = []
        for sym, pos in self._broker._positions.items():
            current = float(bars.get(sym, {}).get("close", pos["cost_price"]))
            mv = pos["qty"] * current
            out.append({
                "symbol": sym, "name": sym, "qty": pos["qty"],
                "cost_price": pos["cost_price"], "current_price": current,
                "market_value": mv,
                "unrealized_pl": mv - pos["qty"] * pos["cost_price"],
                "is_option": False, "currency": "USD", "side": "LONG",
            })
        return out

    async def get_balance(self) -> dict:
        positions = await self.get_positions()
        market_value = sum(p["market_value"] for p in positions)
        return {
            "cash": self._broker._cash,
            "buying_power": self._broker._cash,
            "total_assets": self._broker._cash + market_value,
            "market_value": market_value,
            "currency": "USD",
        }

    async def get_account_info(self) -> dict:
        return {
            "account_id": "BACKTEST",
            "currency": "USD",
            "environment": "backtest",
        }


class _BacktestOrders:
    def __init__(self, broker: BacktestBroker) -> None:
        self._broker = broker

    async def place_order(self, spec: OrderSpec) -> str:
        if spec.is_option:
            raise MoomooOrderError("backtest mode: stock-only", error_code=-1)
        order_id = self._broker._next_order_id()
        self._broker._pending.append(PendingOrder(
            order_id=order_id,
            symbol=spec.symbol,
            side=str(spec.side.value).upper(),
            qty=int(spec.qty),
            order_type=str(spec.order_type.value).upper(),
            limit_price=float(spec.price) if spec.order_type.value == "limit" else None,
        ))
        return order_id

    async def cancel_order(self, order_id: str) -> None:
        self._broker._pending = [
            o for o in self._broker._pending if o.order_id != order_id
        ]

    async def modify_order(self, order_id: str, qty: int, price: float) -> None:
        for o in self._broker._pending:
            if o.order_id == order_id:
                o.qty = qty
                o.limit_price = price
                return

    async def get_orders(self, status: OrderStatus) -> list[dict]:
        if status == OrderStatus.FILLED:
            return list(self._broker._filled)
        if status == OrderStatus.PENDING:
            return [
                {"order_id": o.order_id, "symbol": o.symbol, "side": o.side,
                 "qty": o.qty, "filled_qty": 0, "price": o.limit_price or 0.0,
                 "avg_fill_price": 0.0, "status": OrderStatus.PENDING,
                 "name": o.symbol, "order_type": o.order_type,
                 "created_at": str(self._broker._clock.now())}
                for o in self._broker._pending
            ]
        return []

    async def subscribe_fills(self, callback: Callable[[dict], None]) -> None:
        self._broker._fill_callbacks.append(callback)

    async def subscribe_order_updates(self, callback: Callable[[dict], None]) -> None:
        self._broker._order_update_callbacks.append(callback)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backtest/test_broker.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backtest/broker.py tests/backtest/test_broker.py
git commit -m "feat: add BacktestBroker composing MarketData/Account/Orders interfaces"
```

---

### Task 6: BacktestRunner

**Files:**
- Create: `backtest/runner.py`
- Create: `tests/backtest/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/backtest/test_runner.py`:

```python
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
    # Should call tick at 9:30, 9:35, 9:40 (4 ticks before exiting at 9:45)
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
    result = await runner.run()
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
    # Final dream is forced at end regardless of cadence
    assert engine.run_dream_if_due.await_count >= 1


async def test_runner_skips_non_trading_days(deps):
    broker, engine, calendar, market_hours, run_dir = deps
    # Calendar says day 1 is NOT trading, day 2 IS trading
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
    # Should have ticked on Jan 16 but not Jan 15
    tick_dates = {call.kwargs["now"].date().isoformat() for call in engine.tick.await_args_list}
    assert "2026-01-15" not in tick_dates
    assert "2026-01-16" in tick_dates


async def test_runner_stops_when_engine_halted(deps):
    broker, engine, calendar, market_hours, run_dir = deps
    # halt after first tick
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
    # Should not run all 78 possible ticks
    assert engine.tick.await_count < 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backtest/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `backtest/runner.py`:

```python
import json
from datetime import datetime, timedelta
from pathlib import Path

from engine.config import MarketHoursConfig
from engine.calendar import TradingCalendar
from engine.market_hours import is_market_open

from backtest.broker import BacktestBroker
from backtest.clock import SimulatedClock


class BacktestRunner:
    def __init__(
        self, broker, engine, clock: SimulatedClock,
        calendar: TradingCalendar, market_hours: MarketHoursConfig,
        run_dir: Path, start: datetime, end: datetime,
        heartbeat_minutes: int, dream_every_n_days: int,
    ) -> None:
        self._broker = broker
        self._engine = engine
        self._clock = clock
        self._calendar = calendar
        self._market_hours = market_hours
        self._run_dir = Path(run_dir)
        self._start = start
        self._end = end
        self._heartbeat_minutes = heartbeat_minutes
        self._dream_every_n_days = dream_every_n_days

    async def run(self) -> dict:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        last_dream_date = None
        tick_count = 0
        ticks_skipped_closed = 0

        while self._clock.now() <= self._end:
            now = self._clock.now()
            if not is_market_open(now, self._market_hours, self._calendar):
                self._clock.advance(timedelta(minutes=self._heartbeat_minutes))
                ticks_skipped_closed += 1
                continue

            self._broker.process_bar(now)

            if (last_dream_date is None
                    or (now.date() - last_dream_date).days >= self._dream_every_n_days):
                await self._engine.run_dream_if_due(now=now)
                last_dream_date = now.date()

            await self._engine.tick(now=now)
            tick_count += 1

            if getattr(self._engine, "halted", False):
                break

            self._clock.advance(timedelta(minutes=self._heartbeat_minutes))

        # Final consolidation dream
        await self._engine.run_dream_if_due(now=self._clock.now())

        manifest = {
            "start": self._start.isoformat(),
            "end": self._end.isoformat(),
            "heartbeat_minutes": self._heartbeat_minutes,
            "dream_every_n_days": self._dream_every_n_days,
            "tick_count": tick_count,
            "ticks_skipped_market_closed": ticks_skipped_closed,
            "halted": bool(getattr(self._engine, "halted", False)),
        }
        (self._run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backtest/test_runner.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backtest/runner.py tests/backtest/test_runner.py
git commit -m "feat: add BacktestRunner replay loop"
```

---

### Task 7: Promotion command

**Files:**
- Create: `backtest/promote.py`
- Create: `tests/backtest/test_promote.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/backtest/test_promote.py`:

```python
import json
from pathlib import Path

import pytest

from backtest.promote import promote_learnings


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(e) for e in entries) + "\n"
    path.write_text(body)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


async def test_promote_appends_entries_to_live(tmp_path):
    live = tmp_path / "live"
    backtest_run = tmp_path / "live" / "backtests" / "run1"

    _write_jsonl(live / "learnings" / "learnings.jsonl", [
        {"id": "live-1", "active": True, "observation": "live entry",
         "category": "general", "evidence": "...", "created_at": "2026-05-01"},
    ])
    _write_jsonl(backtest_run / "learnings" / "learnings.jsonl", [
        {"id": "bt-1", "active": True, "observation": "bt entry",
         "category": "general", "evidence": "...", "created_at": "2026-05-04"},
    ])

    summary = await promote_learnings(run_id="run1", live_root=live)

    final = _read_jsonl(live / "learnings" / "learnings.jsonl")
    assert len(final) == 2
    bt_entry = next(e for e in final if "bt-" in e["id"])
    assert bt_entry["source"] == "backtest:run1"
    assert bt_entry["confidence"] == "low"


async def test_promote_handles_id_collision(tmp_path):
    live = tmp_path / "live"
    backtest_run = tmp_path / "live" / "backtests" / "run1"

    _write_jsonl(live / "learnings" / "learnings.jsonl", [
        {"id": "shared", "active": True, "observation": "live",
         "category": "general", "evidence": "...", "created_at": "2026-05-01"},
    ])
    _write_jsonl(backtest_run / "learnings" / "learnings.jsonl", [
        {"id": "shared", "active": True, "observation": "bt",
         "category": "general", "evidence": "...", "created_at": "2026-05-04"},
    ])

    await promote_learnings(run_id="run1", live_root=live)

    final = _read_jsonl(live / "learnings" / "learnings.jsonl")
    assert len(final) == 2
    bt_entry = next(e for e in final if e["observation"] == "bt")
    assert bt_entry["id"] == "shared_bt_run1"
    assert bt_entry["original_id"] == "shared"


async def test_promote_raises_when_run_directory_missing(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    with pytest.raises(FileNotFoundError):
        await promote_learnings(run_id="nonexistent", live_root=live)


async def test_promote_handles_empty_live_learnings(tmp_path):
    live = tmp_path / "live"
    backtest_run = tmp_path / "live" / "backtests" / "run1"
    _write_jsonl(backtest_run / "learnings" / "learnings.jsonl", [
        {"id": "bt-1", "active": True, "observation": "bt entry",
         "category": "general", "evidence": "...", "created_at": "2026-05-04"},
    ])
    await promote_learnings(run_id="run1", live_root=live)
    final = _read_jsonl(live / "learnings" / "learnings.jsonl")
    assert len(final) == 1
    assert final[0]["source"] == "backtest:run1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backtest/test_promote.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Create `backtest/promote.py`:

```python
import json
from pathlib import Path


async def promote_learnings(run_id: str, live_root: Path) -> dict:
    live_root = Path(live_root)
    backtest_path = live_root / "backtests" / run_id / "learnings" / "learnings.jsonl"
    if not backtest_path.exists():
        raise FileNotFoundError(f"backtest learnings not found: {backtest_path}")

    live_path = live_root / "learnings" / "learnings.jsonl"
    live_path.parent.mkdir(parents=True, exist_ok=True)

    live_entries = _read_jsonl(live_path)
    bt_entries = _read_jsonl(backtest_path)
    live_ids = {e["id"] for e in live_entries}

    imported = 0
    for entry in bt_entries:
        new_entry = dict(entry)
        new_entry["source"] = f"backtest:{run_id}"
        if "confidence" not in new_entry:
            new_entry["confidence"] = "low"
        if new_entry["id"] in live_ids:
            new_entry["original_id"] = new_entry["id"]
            new_entry["id"] = f"{new_entry['id']}_bt_{run_id}"
        live_entries.append(new_entry)
        live_ids.add(new_entry["id"])
        imported += 1

    body = "\n".join(json.dumps(e, default=str) for e in live_entries) + "\n"
    live_path.write_text(body)

    return {"imported": imported, "live_total": len(live_entries)}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backtest/test_promote.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backtest/promote.py tests/backtest/test_promote.py
git commit -m "feat: add promote_learnings to copy backtest learnings into live system"
```

---

### Task 8: PromptBuilder note about backtest-source learnings

**Files:**
- Modify: `agent/prompt.py`

- [ ] **Step 1: Update the system prompt**

In `agent/prompt.py`, find the `_SYSTEM_PROMPT` and locate the existing note about `learnings/learnings.jsonl`. Append this sentence to that paragraph:

```
Entries with `source` starting `backtest:` came from offline simulation —
treat them with appropriate caution and validate against real fills before
relying heavily on them.
```

The full updated paragraph should read:

```python
"""...
Past performance and your accumulated learnings:
- performance.json — your track record across windows (today, last 7 / 30 days,
  all-time, per-symbol breakdown), plus open-position unrealized P&L.
- learnings/learnings.jsonl — observations from your prior reflections. Active
  entries (active=true) represent your current beliefs about what works and
  what doesn't. Consult both before sizing positions and choosing trades.
  Entries with `source` starting `backtest:` came from offline simulation —
  treat them with appropriate caution and validate against real fills before
  relying heavily on them.
..."""
```

- [ ] **Step 2: Run prompt tests to verify nothing broke**

Run: `pytest tests/agent/test_prompt.py -v`
Expected: all pass (no new tests required; the existing tests don't lock in this exact wording).

- [ ] **Step 3: Commit**

```bash
git add agent/prompt.py
git commit -m "feat: prompt notes that backtest-source learnings are lower confidence"
```

---

### Task 9: CLI entry point + final integration check

**Files:**
- Create: `backtest/cli.py`
- Create: `backtest/__main__.py`

- [ ] **Step 1: Create the CLI module**

Create `backtest/cli.py`:

```python
import argparse
import asyncio
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from agent.dream import DreamRunner
from agent.prompt import PromptBuilder
from agent.runner import AgentRunner
from analytics.ledger import Ledger
from analytics.performance import compute_performance
from connector.connection import ConnectionManager, TradingMode
from connector.market_data import MarketData
from data.collector import Collector
from data.store import DataStore
from engine.calendar import TradingCalendar
from engine.config import HistoryConfig, OptionsConfig, load_config
from engine.executor import ProposalExecutor
from engine.loop import Engine
from engine.safe_orders import SafeOrders

from backtest.broker import BacktestBroker
from backtest.cache import HistoricalDataCache
from backtest.clock import SimulatedClock
from backtest.promote import promote_learnings
from backtest.runner import BacktestRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backtest", description="Run pennytrader backtests")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run a backtest")
    run.add_argument("--start", required=True, help="YYYY-MM-DD")
    run.add_argument("--end", required=True, help="YYYY-MM-DD")
    run.add_argument("--watchlist", required=True, help="Comma-separated symbols")
    run.add_argument("--heartbeat-minutes", type=int, default=5)
    run.add_argument("--dream-every-n-days", type=int, default=7)
    run.add_argument("--starting-cash", type=float, default=100000.0)
    run.add_argument("--bar-interval", default="1m")
    run.add_argument("--label", default="run")
    run.add_argument("--config", default="config.yaml")

    promote = sub.add_parser("promote-learnings", help="Promote backtest learnings to live")
    promote.add_argument("run_id")
    promote.add_argument("--live-root", default=".trading_data")
    promote.add_argument("--yes", action="store_true", help="Skip confirmation")

    return parser


async def _run_backtest(args) -> int:
    config = load_config(Path(args.config))
    watchlist = [s.strip() for s in args.watchlist.split(",") if s.strip()]
    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)
    tz = ZoneInfo(config.market_hours.tz)
    start_dt = datetime.combine(start_d, datetime.min.time(), tzinfo=tz).replace(
        hour=int(config.market_hours.open.split(":")[0]),
        minute=int(config.market_hours.open.split(":")[1]),
    )
    end_dt = datetime.combine(end_d, datetime.min.time(), tzinfo=tz).replace(
        hour=int(config.market_hours.close.split(":")[0]),
        minute=int(config.market_hours.close.split(":")[1]),
    )

    run_id = f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}_{args.label}"
    live_root = Path(".trading_data")
    run_dir = live_root / "backtests" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_store = DataStore(run_dir)
    run_store.ensure_dirs()

    cache_dir = live_root / "historical_cache"

    # Pre-fetch historical data via the live connector
    print(f"Pre-flight: ensuring cached bars for {watchlist} from {start_d} to {end_d}...")
    cache = HistoricalDataCache(cache_dir=cache_dir)
    mode = TradingMode.PAPER
    async with ConnectionManager(mode=mode) as conn:
        live_md = MarketData(conn)
        for sym in watchlist:
            await cache.ensure_range(
                market_data=live_md, symbol=sym, interval=args.bar_interval,
                start=start_d, end=end_d,
            )

    # Build the backtest broker
    clock = SimulatedClock(start=start_dt)
    broker = BacktestBroker(
        cache=cache, clock=clock,
        watchlist=watchlist, interval=args.bar_interval,
        starting_cash=args.starting_cash,
    )

    # Build the calendar (using the broker's market_data, which derives trading days from the cache)
    calendar = TradingCalendar(market_data=broker.market_data, market="US")
    await calendar.load(start=start_d, end=end_d)

    # Build the rest of the wiring (mirrors main.py but with broker substitution)
    history_config = HistoryConfig(interval=args.bar_interval, lookback_hours=6.5)
    options_config = OptionsConfig(nearest_expiries=2)

    def _upcoming_expiries(symbol, n):
        # backtests can't trade options anyway; provide empty
        return []

    collector = Collector(
        store=run_store, market_data=broker.market_data, options=broker.market_data,
        account=broker.account, orders=broker.orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=_upcoming_expiries,
    )

    fill_buffer: list[dict] = []
    await broker.orders.subscribe_fills(lambda fill: fill_buffer.append(fill))
    order_update_buffer: list[dict] = []
    await broker.orders.subscribe_order_updates(lambda u: order_update_buffer.append(u))

    safe_orders = SafeOrders(
        orders=broker.orders, account=broker.account,
        max_position_size_pct=config.safety.max_position_size_pct,
    )
    executor = ProposalExecutor(safe_orders=safe_orders)
    runner = AgentRunner(timeout_seconds=config.claude_timeout_seconds)
    prompt_builder = PromptBuilder(
        store=run_store, watchlist=watchlist,
        history_interval=args.bar_interval,
    )

    class _LogWriter:
        def __init__(self, store): self._store = store
        def write(self, entry: dict) -> None:
            from datetime import datetime as dt
            path = self._store.decision_log_path(dt.utcnow().date())
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(json.dumps(entry, default=str) + "\n")

    log_writer = _LogWriter(run_store)

    ledger = Ledger(store=run_store)
    dream_runner = DreamRunner(
        ledger=ledger, performance_fn=compute_performance,
        runner=runner, store=run_store, log_writer=log_writer,
        account=broker.account, orders=broker.orders,
    )

    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=broker.account, orders=broker.orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=run_store, calendar=calendar,
        dream_runner=dream_runner, log_writer=log_writer,
    )

    bt_runner = BacktestRunner(
        broker=broker, engine=engine, clock=clock, calendar=calendar,
        market_hours=config.market_hours, run_dir=run_dir,
        start=start_dt, end=end_dt,
        heartbeat_minutes=args.heartbeat_minutes,
        dream_every_n_days=args.dream_every_n_days,
    )

    print(f"Running backtest. Output: {run_dir}")
    manifest = await bt_runner.run()
    print(json.dumps(manifest, indent=2))
    print(f"Done. Run directory: {run_dir}")
    return 0


async def _promote(args) -> int:
    if not args.yes:
        ans = input(f"Promote learnings from run {args.run_id} into {args.live_root}? [y/N] ")
        if ans.strip().lower() != "y":
            print("Aborted.")
            return 1
    summary = await promote_learnings(run_id=args.run_id, live_root=Path(args.live_root))
    print(json.dumps(summary, indent=2))
    return 0


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(_run_backtest(args))
    if args.cmd == "promote-learnings":
        return asyncio.run(_promote(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Create `backtest/__main__.py`**

```python
import sys
from backtest.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify imports resolve cleanly**

Run:
```bash
python3 -c "
from backtest.cache import HistoricalDataCache
from backtest.clock import SimulatedClock
from backtest.matcher import OrderMatcher, PendingOrder
from backtest.broker import BacktestBroker
from backtest.runner import BacktestRunner
from backtest.promote import promote_learnings
from backtest.cli import main
print('All imports OK')
"
```
Expected: `All imports OK`

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: all tests pass (previous 172 + ~32 new ≈ 204), no warnings.

- [ ] **Step 5: Smoke-test CLI argument parsing**

Run:
```bash
python -m backtest --help
python -m backtest run --help
python -m backtest promote-learnings --help
```
Expected: each prints usage info without crashing.

- [ ] **Step 6: Commit**

```bash
git add backtest/cli.py backtest/__main__.py
git commit -m "feat: add backtest CLI for run and promote-learnings commands"
```
