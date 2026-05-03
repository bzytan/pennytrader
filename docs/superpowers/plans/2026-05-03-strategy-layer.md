# Strategy Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the autonomous trading agent layer that drives a heartbeat loop, collects market data to files, and invokes `claude --print` for trading decisions backed by the user's Claude subscription.

**Architecture:** Four-layer system: engine (heartbeat + orchestration + safety), data collector (writes market data to files), agent (subprocess wrapper around `claude --print`), and a single `config.yaml` controlling tunable parameters. The agent reads file paths rather than inline data and calls a size-guarded `SafeOrders` to execute trades.

**Tech Stack:** Python 3.11+, moomoo-api, pyyaml, pytest, pytest-asyncio. The `claude` CLI must be installed on the host running the engine (runtime requirement, not a Python dependency).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modify | Add `pyyaml` dependency |
| `connector/orders.py` | Modify | Add `Orders.subscribe_fills` |
| `tests/connector/test_orders.py` | Modify | Add tests for `subscribe_fills` |
| `engine/__init__.py` | Create | Package marker |
| `engine/config.py` | Create | Config dataclasses + `load_config` |
| `engine/market_hours.py` | Create | `is_market_open`, `next_open` |
| `engine/safe_orders.py` | Create | `SafeOrders` wrapper enforcing size limit |
| `engine/loop.py` | Create | `Engine` orchestrator, circuit breaker, tick guard |
| `data/__init__.py` | Create | Package marker |
| `data/store.py` | Create | Path constants + atomic write helper |
| `data/collector.py` | Create | `Collector.collect()` — writes all data files |
| `agent/__init__.py` | Create | Package marker |
| `agent/runner.py` | Create | `AgentRunner` — subprocess wrapper |
| `agent/prompt.py` | Create | `PromptBuilder` — assembles prompt per tick |
| `tests/engine/__init__.py` | Create | Test package marker |
| `tests/engine/test_config.py` | Create | Config parsing tests |
| `tests/engine/test_market_hours.py` | Create | Market hours tests |
| `tests/engine/test_safe_orders.py` | Create | Size guard tests |
| `tests/engine/test_loop.py` | Create | Engine orchestration tests |
| `tests/data/__init__.py` | Create | Test package marker |
| `tests/data/test_store.py` | Create | Path/store tests |
| `tests/data/test_collector.py` | Create | Collector output tests |
| `tests/agent/__init__.py` | Create | Test package marker |
| `tests/agent/test_runner.py` | Create | Subprocess tests |
| `tests/agent/test_prompt.py` | Create | Prompt building tests |
| `config.yaml.example` | Create | Sample config |
| `main.py` | Create | Entry point |

---

### Task 1: Add `subscribe_fills` to connector Orders

**Files:**
- Modify: `connector/orders.py`
- Modify: `tests/connector/test_orders.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/connector/test_orders.py`:

```python
from unittest.mock import patch


async def test_subscribe_fills_registers_handler(mock_conn):
    orders = Orders(mock_conn)
    received = []
    await orders.subscribe_fills(lambda fill: received.append(fill))

    mock_conn.trade_ctx.set_handler.assert_called_once()


async def test_subscribe_fills_dispatches_fill_to_callback(mock_conn):
    import asyncio
    import moomoo as ft

    orders = Orders(mock_conn)
    received: list[dict] = []
    done = asyncio.Event()

    def callback(fill):
        received.append(fill)
        done.set()

    await orders.subscribe_fills(callback)

    handler = mock_conn.trade_ctx.set_handler.call_args.args[0]
    fill_df = pd.DataFrame([{
        "order_id": "ORD001",
        "code": "US.AAPL",
        "trd_side": "BUY",
        "qty": 10,
        "price": 150.0,
        "create_time": "2024-01-15 10:00:00",
    }])
    handler.on_recv_rsp_for_test = lambda: handler.on_recv_rsp(fill_df)
    handler.on_recv_rsp(("ignored", fill_df))

    await asyncio.wait_for(done.wait(), timeout=1.0)
    assert received[0]["order_id"] == "ORD001"
    assert received[0]["symbol"] == "US.AAPL"
    assert received[0]["qty"] == 10
    assert received[0]["price"] == 150.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/connector/test_orders.py::test_subscribe_fills_registers_handler -v`
Expected: FAIL with `AttributeError` or test error indicating `subscribe_fills` does not exist.

- [ ] **Step 3: Add the implementation**

In `connector/orders.py`, add at the top of the imports:

```python
from collections.abc import Callable
```

Append to the `Orders` class:

```python
    async def subscribe_fills(self, callback: Callable[[dict], None]) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        class _FillHandler(ft.TradeDealHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code == ft.RET_OK and not content.empty:
                    for _, row in content.iterrows():
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "order_id": str(row["order_id"]),
                            "symbol": row["code"],
                            "side": row["trd_side"],
                            "qty": int(row["qty"]),
                            "price": float(row["price"]),
                            "filled_at": row["create_time"],
                        })
                return ret_code, content

        self._conn.trade_ctx.set_handler(_FillHandler())
        if not hasattr(self, "_fill_tasks"):
            self._fill_tasks: list[asyncio.Task] = []
        task = asyncio.create_task(self._dispatch_fills(queue, callback))
        self._fill_tasks.append(task)

    @staticmethod
    async def _dispatch_fills(queue: asyncio.Queue, callback: Callable[[dict], None]) -> None:
        while True:
            data = await queue.get()
            try:
                callback(data)
            except Exception:
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/connector/test_orders.py -v`
Expected: 12 passed (10 original + 2 new).

- [ ] **Step 5: Commit**

```bash
git add connector/orders.py tests/connector/test_orders.py
git commit -m "feat: add subscribe_fills to Orders module"
```

---

### Task 2: Add pyyaml dependency and project setup

**Files:**
- Modify: `pyproject.toml`
- Create: `engine/__init__.py`
- Create: `data/__init__.py`
- Create: `agent/__init__.py`
- Create: `tests/engine/__init__.py`
- Create: `tests/data/__init__.py`
- Create: `tests/agent/__init__.py`

- [ ] **Step 1: Update pyproject.toml**

Modify the `dependencies` and `[tool.setuptools.packages.find]` sections:

```toml
[project]
name = "pennytrader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "moomoo-api>=6.0.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["."]
include = ["connector*", "engine*", "data*", "agent*"]
```

- [ ] **Step 2: Create package init files**

```bash
mkdir -p engine data agent tests/engine tests/data tests/agent
touch engine/__init__.py data/__init__.py agent/__init__.py
touch tests/engine/__init__.py tests/data/__init__.py tests/agent/__init__.py
```

- [ ] **Step 3: Install dependencies**

```bash
pip install -e ".[dev]"
```

Expected: pyyaml installs, all packages re-discovered.

- [ ] **Step 4: Verify pytest still discovers existing tests**

Run: `pytest tests/ --collect-only -q 2>&1 | tail -5`
Expected: no errors, existing 52 tests still collected.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml engine/__init__.py data/__init__.py agent/__init__.py tests/engine/__init__.py tests/data/__init__.py tests/agent/__init__.py
git commit -m "chore: scaffold engine, data, and agent packages with pyyaml dep"
```

---

### Task 3: Config dataclasses and loader

**Files:**
- Create: `engine/config.py`
- Create: `tests/engine/test_config.py`
- Create: `config.yaml.example`

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_config.py`:

```python
import os
from pathlib import Path

import pytest
import yaml

from engine.config import Config, MarketHoursConfig, SafetyConfig, load_config


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _valid_config_dict() -> dict:
    return {
        "mode": "paper",
        "heartbeat_interval_seconds": 60,
        "claude_timeout_seconds": 120,
        "market_hours": {"open": "09:30", "close": "16:00", "tz": "America/New_York"},
        "watchlist": ["AAPL", "SPY"],
        "history": {"interval": "1m", "lookback_hours": 6.5},
        "options": {"nearest_expiries": 2},
        "safety": {
            "max_position_size_pct": 5.0,
            "daily_loss_threshold_pct": 5.0,
            "max_consecutive_agent_failures": 3,
        },
    }


def test_load_config_returns_typed_config(tmp_path):
    path = _write_yaml(tmp_path, _valid_config_dict())
    config = load_config(path)
    assert isinstance(config, Config)
    assert config.mode == "paper"
    assert config.heartbeat_interval_seconds == 60
    assert config.watchlist == ["AAPL", "SPY"]
    assert isinstance(config.market_hours, MarketHoursConfig)
    assert config.market_hours.open == "09:30"
    assert isinstance(config.safety, SafetyConfig)
    assert config.safety.max_position_size_pct == 5.0


def test_load_config_paper_mode_does_not_require_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PENNYTRADER_LIVE", raising=False)
    path = _write_yaml(tmp_path, _valid_config_dict())
    config = load_config(path)
    assert config.mode == "paper"


def test_load_config_live_mode_requires_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("PENNYTRADER_LIVE", raising=False)
    data = _valid_config_dict()
    data["mode"] = "live"
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="PENNYTRADER_LIVE"):
        load_config(path)


def test_load_config_live_mode_with_env_var_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("PENNYTRADER_LIVE", "1")
    data = _valid_config_dict()
    data["mode"] = "live"
    path = _write_yaml(tmp_path, data)
    config = load_config(path)
    assert config.mode == "live"


def test_load_config_rejects_unknown_mode(tmp_path):
    data = _valid_config_dict()
    data["mode"] = "demo"
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="mode"):
        load_config(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.config'`.

- [ ] **Step 3: Write the implementation**

Create `engine/config.py`:

```python
import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class MarketHoursConfig:
    open: str
    close: str
    tz: str


@dataclass
class HistoryConfig:
    interval: str
    lookback_hours: float


@dataclass
class OptionsConfig:
    nearest_expiries: int


@dataclass
class SafetyConfig:
    max_position_size_pct: float
    daily_loss_threshold_pct: float
    max_consecutive_agent_failures: int


@dataclass
class Config:
    mode: str
    heartbeat_interval_seconds: int
    claude_timeout_seconds: int
    market_hours: MarketHoursConfig
    watchlist: list[str]
    history: HistoryConfig
    options: OptionsConfig
    safety: SafetyConfig


def load_config(path: Path) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    mode = raw["mode"]
    if mode not in ("paper", "live"):
        raise ValueError(f"Invalid mode: {mode!r}. Must be 'paper' or 'live'.")
    if mode == "live" and os.environ.get("PENNYTRADER_LIVE") != "1":
        raise ValueError(
            "Live mode requires PENNYTRADER_LIVE=1 in the environment as a safety check."
        )

    return Config(
        mode=mode,
        heartbeat_interval_seconds=int(raw["heartbeat_interval_seconds"]),
        claude_timeout_seconds=int(raw["claude_timeout_seconds"]),
        market_hours=MarketHoursConfig(**raw["market_hours"]),
        watchlist=list(raw["watchlist"]),
        history=HistoryConfig(**raw["history"]),
        options=OptionsConfig(**raw["options"]),
        safety=SafetyConfig(**raw["safety"]),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Create `config.yaml.example`**

```yaml
mode: paper
heartbeat_interval_seconds: 60
claude_timeout_seconds: 120

market_hours:
  open: "09:30"
  close: "16:00"
  tz: "America/New_York"

watchlist:
  - AAPL
  - SPY
  - TSLA

history:
  interval: "1m"
  lookback_hours: 6.5

options:
  nearest_expiries: 2

safety:
  max_position_size_pct: 5.0
  daily_loss_threshold_pct: 5.0
  max_consecutive_agent_failures: 3
```

- [ ] **Step 6: Commit**

```bash
git add engine/config.py tests/engine/test_config.py config.yaml.example
git commit -m "feat: add config dataclasses and YAML loader with live-mode safety"
```

---

### Task 4: Market hours helpers

**Files:**
- Create: `engine/market_hours.py`
- Create: `tests/engine/test_market_hours.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_market_hours.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.config import MarketHoursConfig
from engine.market_hours import is_market_open, next_open


CONFIG = MarketHoursConfig(open="09:30", close="16:00", tz="America/New_York")
NY = ZoneInfo("America/New_York")


def test_is_market_open_during_hours():
    now = datetime(2024, 1, 16, 10, 30, tzinfo=NY)  # Tuesday 10:30am ET
    assert is_market_open(now, CONFIG) is True


def test_is_market_open_before_open():
    now = datetime(2024, 1, 16, 9, 0, tzinfo=NY)  # Tuesday 9:00am ET
    assert is_market_open(now, CONFIG) is False


def test_is_market_open_after_close():
    now = datetime(2024, 1, 16, 16, 30, tzinfo=NY)  # Tuesday 4:30pm ET
    assert is_market_open(now, CONFIG) is False


def test_is_market_open_on_weekend():
    now = datetime(2024, 1, 13, 10, 30, tzinfo=NY)  # Saturday
    assert is_market_open(now, CONFIG) is False


def test_is_market_open_handles_utc_input():
    # 14:30 UTC on Tuesday = 09:30 ET (start of session in standard time)
    now = datetime(2024, 1, 16, 14, 30, tzinfo=ZoneInfo("UTC"))
    assert is_market_open(now, CONFIG) is True


def test_next_open_before_today_open():
    now = datetime(2024, 1, 16, 7, 0, tzinfo=NY)  # Tuesday early morning
    nxt = next_open(now, CONFIG)
    assert nxt.date() == now.date()
    assert nxt.hour == 9 and nxt.minute == 30


def test_next_open_after_today_close():
    now = datetime(2024, 1, 16, 17, 0, tzinfo=NY)  # Tuesday after close
    nxt = next_open(now, CONFIG)
    assert nxt.date().isoformat() == "2024-01-17"  # Wednesday
    assert nxt.hour == 9 and nxt.minute == 30


def test_next_open_friday_evening_skips_to_monday():
    now = datetime(2024, 1, 19, 17, 0, tzinfo=NY)  # Friday after close
    nxt = next_open(now, CONFIG)
    assert nxt.date().isoformat() == "2024-01-22"  # Monday
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_market_hours.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.market_hours'`.

- [ ] **Step 3: Write the implementation**

Create `engine/market_hours.py`:

```python
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import MarketHoursConfig


def _parse_time(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def is_market_open(now: datetime, config: MarketHoursConfig) -> bool:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    if local.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_t = _parse_time(config.open)
    close_t = _parse_time(config.close)
    return open_t <= local.time() < close_t


def next_open(now: datetime, config: MarketHoursConfig) -> datetime:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    open_t = _parse_time(config.open)

    candidate = local.replace(
        hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0
    )
    if local >= candidate:
        candidate = candidate + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate = candidate + timedelta(days=1)
    return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_market_hours.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/market_hours.py tests/engine/test_market_hours.py
git commit -m "feat: add market hours helpers for US equity sessions"
```

---

### Task 5: Data store paths and atomic write helper

**Files:**
- Create: `data/store.py`
- Create: `tests/data/test_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/data/test_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/data/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.store'`.

- [ ] **Step 3: Write the implementation**

Create `data/store.py`:

```python
import os
from datetime import date
from pathlib import Path


class DataStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def ensure_dirs(self) -> None:
        for sub in ("quotes", "history", "options", "account", "log"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def quote_path(self, symbol: str) -> Path:
        return self.root / "quotes" / f"{symbol}.json"

    def history_path(self, symbol: str, interval: str) -> Path:
        return self.root / "history" / f"{symbol}_{interval}.csv"

    def option_chain_path(self, symbol: str, expiry: date) -> Path:
        return self.root / "options" / f"{symbol}_{expiry.isoformat()}.json"

    def positions_path(self) -> Path:
        return self.root / "account" / "positions.json"

    def balance_path(self) -> Path:
        return self.root / "account" / "balance.json"

    def open_orders_path(self) -> Path:
        return self.root / "account" / "orders_open.json"

    def recent_fills_path(self) -> Path:
        return self.root / "account" / "recent_fills.json"

    def decision_log_path(self, day: date) -> Path:
        return self.root / "log" / f"decisions-{day.isoformat()}.jsonl"

    def atomic_write_text(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content)
        os.replace(tmp, target)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/data/test_store.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add data/store.py tests/data/test_store.py
git commit -m "feat: add DataStore with path conventions and atomic writes"
```

---

### Task 6: Data collector

**Files:**
- Create: `data/collector.py`
- Create: `tests/data/test_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/data/test_collector.py`:

```python
import json
from datetime import date
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
    await collector.collect(["AAPL"])

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
    await collector.collect(["AAPL"])

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
    await collector.collect(["AAPL"])

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
    await collector.collect(["AAPL"])

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
    await collector.collect(["AAPL", "SPY"])

    assert store.quote_path("AAPL").exists()
    assert store.quote_path("SPY").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/data/test_collector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.collector'`.

- [ ] **Step 3: Write the implementation**

Create `data/collector.py`:

```python
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta

import moomoo as ft

from connector.account import Account
from connector.market_data import MarketData
from connector.options import Options
from connector.orders import Orders, OrderStatus
from engine.config import HistoryConfig, OptionsConfig

from .store import DataStore


class Collector:
    def __init__(
        self,
        store: DataStore,
        market_data: MarketData,
        options: Options,
        account: Account,
        orders: Orders,
        history_config: HistoryConfig,
        options_config: OptionsConfig,
        upcoming_expiries_provider: Callable[[str, int], list[date]],
    ) -> None:
        self._store = store
        self._market_data = market_data
        self._options = options
        self._account = account
        self._orders = orders
        self._history_config = history_config
        self._options_config = options_config
        self._upcoming_expiries = upcoming_expiries_provider

    async def collect(self, watchlist: list[str]) -> None:
        for symbol in watchlist:
            await self._write_quote(symbol)
            await self._write_history(symbol)
            await self._write_options(symbol)
        await self._write_account()

    async def _write_quote(self, symbol: str) -> None:
        quote = await self._market_data.get_quote(symbol)
        self._store.atomic_write_text(
            self._store.quote_path(symbol), json.dumps(quote, indent=2)
        )

    async def _write_history(self, symbol: str) -> None:
        end = datetime.now().date()
        start = end - timedelta(days=2)
        ktype = _interval_to_ktype(self._history_config.interval)
        rows = await self._market_data.get_price_history(symbol, start, end, ktype)
        header = "time,open,close,high,low,volume,turnover"
        body = "\n".join(
            f"{r['time']},{r['open']},{r['close']},{r['high']},{r['low']},{r['volume']},{r['turnover']}"
            for r in rows
        )
        self._store.atomic_write_text(
            self._store.history_path(symbol, self._history_config.interval),
            header + "\n" + body + "\n",
        )

    async def _write_options(self, symbol: str) -> None:
        expiries = self._upcoming_expiries(symbol, self._options_config.nearest_expiries)
        for expiry in expiries:
            chain = await self._options.get_option_chain(symbol, expiry)
            self._store.atomic_write_text(
                self._store.option_chain_path(symbol, expiry),
                json.dumps(chain, indent=2),
            )

    async def _write_account(self) -> None:
        positions = await self._account.get_positions()
        balance = await self._account.get_balance()
        open_orders = await self._orders.get_orders(OrderStatus.PENDING)
        self._store.atomic_write_text(
            self._store.positions_path(), json.dumps(positions, indent=2, default=str)
        )
        self._store.atomic_write_text(
            self._store.balance_path(), json.dumps(balance, indent=2, default=str)
        )
        self._store.atomic_write_text(
            self._store.open_orders_path(),
            json.dumps(open_orders, indent=2, default=str),
        )


def _interval_to_ktype(interval: str) -> "ft.KLType":
    mapping = {
        "1m": ft.KLType.K_1M,
        "5m": ft.KLType.K_5M,
        "15m": ft.KLType.K_15M,
        "1h": ft.KLType.K_60M,
        "1d": ft.KLType.K_DAY,
    }
    if interval not in mapping:
        raise ValueError(f"Unsupported history interval: {interval}")
    return mapping[interval]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/data/test_collector.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add data/collector.py tests/data/test_collector.py
git commit -m "feat: add data Collector that writes market and account state to files"
```

---

### Task 7: Safe orders wrapper

**Files:**
- Create: `engine/safe_orders.py`
- Create: `tests/engine/test_safe_orders.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_safe_orders.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from connector.exceptions import MoomooOrderError
from connector.orders import OrderSpec, OrderType, TradeSide
from engine.safe_orders import SafeOrders


def _make_spec(qty=1, price=100.0, symbol="AAPL"):
    return OrderSpec(
        symbol=symbol, qty=qty, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=price,
    )


@pytest.fixture
def orders():
    o = MagicMock()
    o.place_order = AsyncMock(return_value="ORD001")
    o.cancel_order = AsyncMock()
    o.modify_order = AsyncMock()
    o.get_orders = AsyncMock(return_value=[])
    return o


@pytest.fixture
def account():
    a = MagicMock()
    a.get_balance = AsyncMock(return_value={
        "cash": 10000.0, "buying_power": 20000.0,
        "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD",
    })
    return a


async def test_place_order_within_limit_succeeds(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    result = await safe.place_order(_make_spec(qty=10, price=100.0))  # $1,000 vs $100k account
    assert result == "ORD001"
    orders.place_order.assert_awaited_once()


async def test_place_order_exceeding_limit_raises(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    spec = _make_spec(qty=100, price=100.0)  # $10,000 = 10% of $100k, exceeds 5%
    with pytest.raises(MoomooOrderError, match="exceeds max position size"):
        await safe.place_order(spec)
    orders.place_order.assert_not_awaited()


async def test_place_option_order_uses_contract_size(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    from datetime import date
    spec = OrderSpec(
        symbol="US.AAPL240119C00150000", qty=2, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=5.50,
        expiry=date(2024, 1, 19), strike=150.0,
        option_type=None, contract_size=100,
    )
    # notional = 2 * 5.50 * 100 = $1,100; 1.1% of $100k → within 5%
    await safe.place_order(spec)
    orders.place_order.assert_awaited_once()


async def test_cancel_order_passes_through(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    await safe.cancel_order("ORD001")
    orders.cancel_order.assert_awaited_once_with("ORD001")


async def test_modify_order_re_checks_size(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    with pytest.raises(MoomooOrderError, match="exceeds max position size"):
        await safe.modify_order("ORD001", qty=100, price=100.0)


async def test_get_orders_passes_through(orders, account):
    from connector.orders import OrderStatus
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    await safe.get_orders(OrderStatus.PENDING)
    orders.get_orders.assert_awaited_once_with(OrderStatus.PENDING)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_safe_orders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.safe_orders'`.

- [ ] **Step 3: Write the implementation**

Create `engine/safe_orders.py`:

```python
from connector.account import Account
from connector.exceptions import MoomooOrderError
from connector.orders import OrderSpec, Orders, OrderStatus


class SafeOrders:
    def __init__(
        self,
        orders: Orders,
        account: Account,
        max_position_size_pct: float,
    ) -> None:
        self._orders = orders
        self._account = account
        self._max_pct = max_position_size_pct

    async def place_order(self, spec: OrderSpec) -> str:
        await self._enforce_size(spec.qty, spec.price, spec.contract_size, spec.is_option)
        return await self._orders.place_order(spec)

    async def cancel_order(self, order_id: str) -> None:
        await self._orders.cancel_order(order_id)

    async def modify_order(self, order_id: str, qty: int, price: float) -> None:
        await self._enforce_size(qty, price, contract_size=None, is_option=False)
        await self._orders.modify_order(order_id, qty=qty, price=price)

    async def get_orders(self, status: OrderStatus) -> list[dict]:
        return await self._orders.get_orders(status)

    async def _enforce_size(
        self, qty: int, price: float, contract_size: int | None, is_option: bool
    ) -> None:
        balance = await self._account.get_balance()
        total = float(balance["total_assets"])
        multiplier = float(contract_size) if (is_option and contract_size) else 1.0
        notional = qty * price * multiplier
        limit = total * self._max_pct / 100.0
        if notional > limit:
            raise MoomooOrderError(
                f"Order notional ${notional:,.2f} exceeds max position size "
                f"({self._max_pct}% of ${total:,.2f} = ${limit:,.2f})",
                error_code=-1,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_safe_orders.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/safe_orders.py tests/engine/test_safe_orders.py
git commit -m "feat: add SafeOrders wrapper enforcing per-trade size limit"
```

---

### Task 8: Agent runner

**Files:**
- Create: `agent/runner.py`
- Create: `tests/agent/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_runner.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner import AgentResult, AgentRunner


@pytest.fixture
def runner():
    return AgentRunner(timeout_seconds=5)


async def test_run_returns_result_on_success(runner):
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"agent thinking...\n", b""))
    fake_proc.returncode = 0

    with patch("agent.runner.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        result = await runner.run("test prompt")
    assert isinstance(result, AgentResult)
    assert result.exit_code == 0
    assert "agent thinking" in result.stdout
    assert result.stderr == ""


async def test_run_records_nonzero_exit_code(runner):
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b"oops"))
    fake_proc.returncode = 1
    with patch("agent.runner.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        result = await runner.run("test prompt")
    assert result.exit_code == 1
    assert result.stderr == "oops"


async def test_run_kills_on_timeout():
    runner = AgentRunner(timeout_seconds=0.1)

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(10)
        return (b"", b"")

    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(side_effect=hang)
    fake_proc.kill = MagicMock()
    fake_proc.returncode = None

    with patch("agent.runner.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        result = await runner.run("test prompt")
    assert result.timed_out is True
    fake_proc.kill.assert_called_once()


async def test_run_passes_prompt_via_stdin():
    runner = AgentRunner(timeout_seconds=5)
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    fake_proc.returncode = 0
    create = AsyncMock(return_value=fake_proc)
    with patch("agent.runner.asyncio.create_subprocess_exec", create):
        await runner.run("hello prompt")
    create.assert_called_once()
    args, _kwargs = create.call_args
    assert args[0] == "claude"
    assert "--print" in args
    fake_proc.communicate.assert_awaited_once_with(input=b"hello prompt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.runner'`.

- [ ] **Step 3: Write the implementation**

Create `agent/runner.py`:

```python
import asyncio
from dataclasses import dataclass
from time import monotonic


@dataclass
class AgentResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool


class AgentRunner:
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout = timeout_seconds

    async def run(self, prompt: str) -> AgentResult:
        start = monotonic()
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=self._timeout,
            )
            return AgentResult(
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                duration_seconds=monotonic() - start,
                timed_out=False,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return AgentResult(
                exit_code=-1, stdout="", stderr="agent invocation timed out",
                duration_seconds=monotonic() - start, timed_out=True,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent/test_runner.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/runner.py tests/agent/test_runner.py
git commit -m "feat: add AgentRunner subprocess wrapper for claude --print"
```

---

### Task 9: Agent prompt builder

**Files:**
- Create: `agent/prompt.py`
- Create: `tests/agent/test_prompt.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_prompt.py`:

```python
from datetime import datetime
from pathlib import Path

from data.store import DataStore
from agent.prompt import PromptBuilder


def test_prompt_includes_system_role(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"])
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 10000.0, "buying_power": 20000.0,
                 "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD"},
        positions=[],
        open_orders=[],
        recent_fills=[],
        daily_pnl=0.0,
    )
    assert "autonomous trading agent" in prompt.lower()
    assert "from engine.safe_orders import SafeOrders" in prompt


def test_prompt_includes_account_state(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"])
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 10000.0, "buying_power": 20000.0,
                 "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD"},
        positions=[{"symbol": "US.AAPL", "qty": 10, "cost_price": 145.0}],
        open_orders=[],
        recent_fills=[],
        daily_pnl=250.0,
    )
    assert "10000.0" in prompt or "10,000" in prompt
    assert "US.AAPL" in prompt
    assert "250" in prompt


def test_prompt_includes_data_file_paths_for_each_watchlist_symbol(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL", "SPY"])
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[], recent_fills=[], daily_pnl=0.0,
    )
    assert str(store.quote_path("AAPL")) in prompt
    assert str(store.quote_path("SPY")) in prompt
    assert str(store.history_path("AAPL", "1m")) in prompt or "AAPL_" in prompt


def test_prompt_includes_recent_fills_when_present(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"])
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[],
        recent_fills=[{"order_id": "ORD001", "symbol": "US.AAPL",
                       "side": "BUY", "qty": 10, "price": 150.0,
                       "filled_at": "2024-01-16 10:00:00"}],
        daily_pnl=0.0,
    )
    assert "ORD001" in prompt
    assert "BUY" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent/test_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.prompt'`.

- [ ] **Step 3: Write the implementation**

Create `agent/prompt.py`:

```python
import json
from datetime import datetime
from pathlib import Path

from data.store import DataStore


_SYSTEM_PROMPT = """You are an autonomous trading agent for the pennytrader system.

You manage a real brokerage account. Your goal is to grow capital through informed
decisions about buying/selling stocks and buying single-leg call or put options.

You have full Claude Code tool access: read files, write Python scripts, run them,
and observe results. Market data and account state are written to files before each
of your invocations — read them to understand the current situation.

To execute trades, import and use the size-guarded SafeOrders wrapper:

    from engine.safe_orders import SafeOrders, OrderSpec, OrderStatus, TradeSide, OrderType, OptionType

The wrapper enforces a maximum per-trade size as a percentage of total account value.
Orders that exceed the limit will raise MoomooOrderError — adjust qty and retry if so.

Available trade types:
- Buy or sell stock (OrderSpec with symbol="AAPL", no expiry)
- Buy a call or put option (OrderSpec with symbol set to the contract code, e.g.
  "US.AAPL240119C00150000", and expiry/strike/option_type/contract_size set)

Important:
- Doing nothing is often the right decision. Do not feel obligated to trade.
- Each invocation is stateless — you have no memory of prior ticks. State lives in
  the broker (positions, orders) and the data files.
- Your reasoning and any scripts you run are logged for later review."""


class PromptBuilder:
    def __init__(self, store: DataStore, watchlist: list[str]) -> None:
        self._store = store
        self._watchlist = watchlist

    def build(
        self,
        now: datetime,
        balance: dict,
        positions: list[dict],
        open_orders: list[dict],
        recent_fills: list[dict],
        daily_pnl: float,
    ) -> str:
        state = {
            "time": now.isoformat(),
            "balance": balance,
            "positions": positions,
            "open_orders": open_orders,
            "recent_fills_since_last_tick": recent_fills,
            "daily_pnl": daily_pnl,
        }

        files: dict[str, str] = {
            "positions": str(self._store.positions_path()),
            "balance": str(self._store.balance_path()),
            "open_orders": str(self._store.open_orders_path()),
            "recent_fills": str(self._store.recent_fills_path()),
        }
        for symbol in self._watchlist:
            files[f"quote_{symbol}"] = str(self._store.quote_path(symbol))
            files[f"history_{symbol}"] = str(self._store.history_path(symbol, "1m"))
            files[f"options_dir_{symbol}"] = str(
                self._store.option_chain_path(symbol, _placeholder_date()).parent
            )

        return (
            _SYSTEM_PROMPT
            + "\n\n## Current state\n"
            + json.dumps(state, indent=2, default=str)
            + "\n\n## Data files\n"
            + json.dumps(files, indent=2)
            + "\n\nAssess the situation and decide what to do. Place trades by "
            + "importing SafeOrders and calling place_order, or take no action."
        )


def _placeholder_date():
    from datetime import date
    return date(2000, 1, 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent/test_prompt.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/prompt.py tests/agent/test_prompt.py
git commit -m "feat: add PromptBuilder for per-tick agent prompt assembly"
```

---

### Task 10: Engine loop

**Files:**
- Create: `engine/loop.py`
- Create: `tests/engine/test_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_loop.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.loop'`.

- [ ] **Step 3: Write the implementation**

Create `engine/loop.py`:

```python
from datetime import datetime
from typing import Protocol

from agent.prompt import PromptBuilder
from agent.runner import AgentResult, AgentRunner
from connector.account import Account
from connector.orders import OrderStatus, Orders
from data.collector import Collector

from .config import Config
from .market_hours import is_market_open


class _LogWriter(Protocol):
    def write(self, entry: dict) -> None: ...


class Engine:
    def __init__(
        self,
        config: Config,
        collector: Collector,
        runner: AgentRunner,
        prompt_builder: PromptBuilder,
        account: Account,
        orders: Orders,
        fill_buffer: list[dict],
        log_writer: _LogWriter,
    ) -> None:
        self._config = config
        self._collector = collector
        self._runner = runner
        self._prompt_builder = prompt_builder
        self._account = account
        self._orders = orders
        self._fill_buffer = fill_buffer
        self._log_writer = log_writer

        self._baseline_total_assets: float | None = None
        self._consecutive_failures = 0
        self.circuit_breaker_tripped = False
        self.halted = False

    def set_baseline_total_assets(self, value: float) -> None:
        self._baseline_total_assets = value

    async def tick(self, now: datetime) -> None:
        if self.halted:
            return
        if not is_market_open(now, self._config.market_hours):
            return
        if self.circuit_breaker_tripped:
            return

        await self._collector.collect(self._config.watchlist)

        balance = await self._account.get_balance()
        if self._baseline_total_assets is None:
            self._baseline_total_assets = float(balance["total_assets"])
        daily_pnl = float(balance["total_assets"]) - self._baseline_total_assets

        loss_threshold = (
            self._baseline_total_assets * self._config.safety.daily_loss_threshold_pct / 100.0
        )
        if daily_pnl < -loss_threshold:
            self.circuit_breaker_tripped = True
            self._log_writer.write({
                "event": "circuit_breaker_tripped",
                "time": now.isoformat(),
                "daily_pnl": daily_pnl,
                "threshold": -loss_threshold,
            })
            return

        recent_fills = list(self._fill_buffer)
        self._fill_buffer.clear()

        positions = await self._account.get_positions()
        open_orders = await self._orders.get_orders(OrderStatus.PENDING)

        prompt = self._prompt_builder.build(
            now=now,
            balance=balance,
            positions=positions,
            open_orders=open_orders,
            recent_fills=recent_fills,
            daily_pnl=daily_pnl,
        )

        result: AgentResult = await self._runner.run(prompt)

        self._log_writer.write({
            "event": "agent_tick",
            "time": now.isoformat(),
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "timed_out": result.timed_out,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "daily_pnl": daily_pnl,
            "fills_processed": recent_fills,
        })

        if result.exit_code != 0 or result.timed_out:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._config.safety.max_consecutive_agent_failures:
                self.halted = True
                self._log_writer.write({"event": "halted", "time": now.isoformat()})
        else:
            self._consecutive_failures = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_loop.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/loop.py tests/engine/test_loop.py
git commit -m "feat: add Engine orchestrator with circuit breaker and failure halt"
```

---

### Task 11: Main entry point and final integration check

**Files:**
- Create: `main.py`

- [ ] **Step 1: Write `main.py`**

```python
import asyncio
import json
import signal
from datetime import datetime
from pathlib import Path

from agent.prompt import PromptBuilder
from agent.runner import AgentRunner
from connector.account import Account
from connector.connection import ConnectionManager, TradingMode
from connector.market_data import MarketData
from connector.options import Options
from connector.orders import Orders
from data.collector import Collector
from data.store import DataStore
from engine.config import load_config
from engine.loop import Engine
from engine.market_hours import is_market_open, next_open
from engine.safe_orders import SafeOrders  # noqa: F401  (imported so agent subprocess sees it)


CONFIG_PATH = Path("config.yaml")
DATA_ROOT = Path(".trading_data")


class JsonlLogWriter:
    def __init__(self, store: DataStore) -> None:
        self._store = store

    def write(self, entry: dict) -> None:
        path = self._store.decision_log_path(datetime.utcnow().date())
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def _upcoming_expiries(symbol: str, n: int):
    # Placeholder: return the next N Fridays. The agent can refine via scripts later.
    from datetime import date, timedelta
    today = date.today()
    days_to_friday = (4 - today.weekday()) % 7 or 7
    first = today + timedelta(days=days_to_friday)
    return [first + timedelta(days=7 * i) for i in range(n)]


async def main() -> None:
    config = load_config(CONFIG_PATH)
    store = DataStore(DATA_ROOT)
    store.ensure_dirs()

    mode = TradingMode.PAPER if config.mode == "paper" else TradingMode.LIVE
    async with ConnectionManager(mode=mode) as conn:
        market_data = MarketData(conn)
        options = Options(conn)
        account = Account(conn)
        orders = Orders(conn)

        collector = Collector(
            store=store, market_data=market_data, options=options,
            account=account, orders=orders,
            history_config=config.history, options_config=config.options,
            upcoming_expiries_provider=_upcoming_expiries,
        )

        fill_buffer: list[dict] = []
        await orders.subscribe_fills(lambda fill: fill_buffer.append(fill))

        runner = AgentRunner(timeout_seconds=config.claude_timeout_seconds)
        prompt_builder = PromptBuilder(store=store, watchlist=config.watchlist)
        log_writer = JsonlLogWriter(store)

        engine = Engine(
            config=config, collector=collector, runner=runner,
            prompt_builder=prompt_builder, account=account, orders=orders,
            fill_buffer=fill_buffer, log_writer=log_writer,
        )

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        while not stop_event.is_set():
            now = datetime.now().astimezone()
            if not is_market_open(now, config.market_hours):
                wakeup = next_open(now, config.market_hours)
                wait = max((wakeup - now).total_seconds(), config.heartbeat_interval_seconds)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                continue
            await engine.tick(now=now)
            if engine.halted:
                break
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=config.heartbeat_interval_seconds
                )
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify package imports cleanly**

```bash
python -c "
from engine.config import load_config
from engine.market_hours import is_market_open
from engine.safe_orders import SafeOrders
from engine.loop import Engine
from data.store import DataStore
from data.collector import Collector
from agent.runner import AgentRunner
from agent.prompt import PromptBuilder
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 3: Run the full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests pass across connector, engine, data, and agent modules. No warnings.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add main entry point that wires the strategy layer together"
```
