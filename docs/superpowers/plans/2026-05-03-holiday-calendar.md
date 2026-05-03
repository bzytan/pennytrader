# Holiday Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "every weekday is a trading day" assumption with a real US equity calendar sourced from moomoo's `request_trading_days` API, including half-day early closes.

**Architecture:** A new `MarketData.get_trading_days` connector method wraps the SDK call. A new `TradingCalendar` class caches the result in memory and answers `is_trading_day` / `session_type` queries. `is_market_open` and `next_open` gain a calendar parameter; the engine constructs and loads the calendar at startup.

**Tech Stack:** Python 3.11+, moomoo-api (`request_trading_days`, `TradeDateMarket`, `TradeDateType`), pytest, pytest-asyncio

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `connector/market_data.py` | Modify | Add `get_trading_days(market, start, end)` |
| `tests/connector/test_market_data.py` | Modify | Add 1 test for the new method |
| `engine/calendar.py` | Create | `TradingCalendar` class with cache + queries |
| `tests/engine/test_calendar.py` | Create | Tests for `TradingCalendar` |
| `engine/config.py` | Modify | Add `early_close: str` to `MarketHoursConfig` |
| `tests/engine/test_config.py` | Modify | Update `_valid_config_dict()` to include `early_close` |
| `config.yaml.example` | Modify | Add `early_close: "13:00"` to `market_hours` |
| `engine/market_hours.py` | Modify | `is_market_open` and `next_open` take `calendar` param; honor half days |
| `tests/engine/test_market_hours.py` | Modify | Update existing tests + add 4 new tests |
| `engine/loop.py` | Modify | `Engine.__init__` takes `calendar`; `tick()` passes it through |
| `tests/engine/test_loop.py` | Modify | Add calendar mock to fixture; new test for non-trading day |
| `main.py` | Modify | Construct + load `TradingCalendar`; pass to Engine and to `is_market_open` / `next_open` |

---

### Task 1: `MarketData.get_trading_days` on the connector

**Files:**
- Modify: `connector/market_data.py`
- Modify: `tests/connector/test_market_data.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/connector/test_market_data.py`:

```python
async def test_get_trading_days_returns_typed_list(mock_conn):
    from datetime import date
    mock_conn.quote_ctx.request_trading_days.return_value = (
        ft.RET_OK,
        [
            {"time": "2024-11-27", "trade_date_type": "WHOLE"},
            {"time": "2024-11-29", "trade_date_type": "MORNING"},
        ],
    )

    md = MarketData(mock_conn)
    result = await md.get_trading_days("US", date(2024, 11, 27), date(2024, 11, 29))

    assert len(result) == 2
    assert result[0]["date"] == date(2024, 11, 27)
    assert result[0]["type"] == "WHOLE"
    assert result[1]["date"] == date(2024, 11, 29)
    assert result[1]["type"] == "MORNING"


async def test_get_trading_days_raises_on_sdk_error(mock_conn):
    from datetime import date
    mock_conn.quote_ctx.request_trading_days.return_value = (ft.RET_ERROR, "Error")

    md = MarketData(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await md.get_trading_days("US", date(2024, 1, 1), date(2024, 12, 31))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/connector/test_market_data.py::test_get_trading_days_returns_typed_list tests/connector/test_market_data.py::test_get_trading_days_raises_on_sdk_error -v`
Expected: FAIL with `AttributeError: 'MarketData' object has no attribute 'get_trading_days'`.

- [ ] **Step 3: Add the implementation**

In `connector/market_data.py`, append to the `MarketData` class:

```python
    async def get_trading_days(
        self, market: str, start: date, end: date
    ) -> list[dict]:
        loop = asyncio.get_running_loop()
        market_enum = getattr(ft.TradeDateMarket, market)
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.request_trading_days(
                market=market_enum,
                start=start.isoformat(),
                end=end.isoformat(),
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        return [
            {"date": date.fromisoformat(row["time"]), "type": row["trade_date_type"]}
            for row in data
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/connector/test_market_data.py -v`
Expected: 9 passed (7 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add connector/market_data.py tests/connector/test_market_data.py
git commit -m "feat: add get_trading_days to MarketData"
```

---

### Task 2: `TradingCalendar` class

**Files:**
- Create: `engine/calendar.py`
- Create: `tests/engine/test_calendar.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_calendar.py`:

```python
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.calendar import TradingCalendar


@pytest.fixture
def market_data():
    md = MagicMock()
    md.get_trading_days = AsyncMock(return_value=[
        {"date": date(2024, 11, 27), "type": "WHOLE"},
        {"date": date(2024, 11, 29), "type": "MORNING"},
        {"date": date(2024, 12, 2), "type": "WHOLE"},
    ])
    return md


async def test_load_populates_cache(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    market_data.get_trading_days.assert_awaited_once_with(
        "US", date(2024, 11, 27), date(2024, 12, 2)
    )


async def test_is_trading_day_returns_true_for_known_day(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_trading_day(date(2024, 11, 27)) is True
    assert cal.is_trading_day(date(2024, 11, 29)) is True


async def test_is_trading_day_returns_false_for_holiday(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    # 2024-11-28 is Thanksgiving — not in the cache
    assert cal.is_trading_day(date(2024, 11, 28)) is False


async def test_is_trading_day_returns_false_for_date_outside_loaded_range(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_trading_day(date(2025, 1, 1)) is False


async def test_is_half_day_for_morning_session(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_half_day(date(2024, 11, 29)) is True


async def test_is_half_day_for_whole_session(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_half_day(date(2024, 11, 27)) is False


async def test_is_half_day_returns_false_for_non_trading_day(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_half_day(date(2024, 11, 28)) is False


async def test_session_type_returns_correct_type(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.session_type(date(2024, 11, 27)) == "WHOLE"
    assert cal.session_type(date(2024, 11, 29)) == "MORNING"


async def test_session_type_returns_none_for_non_trading_day(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.session_type(date(2024, 11, 28)) is None


async def test_load_replaces_existing_cache(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))

    # Re-load with different data
    market_data.get_trading_days = AsyncMock(return_value=[
        {"date": date(2025, 1, 2), "type": "WHOLE"},
    ])
    await cal.load(date(2025, 1, 1), date(2025, 1, 3))

    # Old entry no longer present
    assert cal.is_trading_day(date(2024, 11, 27)) is False
    # New entry present
    assert cal.is_trading_day(date(2025, 1, 2)) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.calendar'`.

- [ ] **Step 3: Write the implementation**

Create `engine/calendar.py`:

```python
from datetime import date
from typing import Literal

from connector.market_data import MarketData


SessionType = Literal["WHOLE", "MORNING", "AFTERNOON"]


class TradingCalendar:
    def __init__(self, market_data: MarketData, market: str = "US") -> None:
        self._market_data = market_data
        self._market = market
        self._cache: dict[date, SessionType] = {}

    async def load(self, start: date, end: date) -> None:
        rows = await self._market_data.get_trading_days(self._market, start, end)
        self._cache = {row["date"]: row["type"] for row in rows}

    def is_trading_day(self, d: date) -> bool:
        return d in self._cache

    def is_half_day(self, d: date) -> bool:
        return self._cache.get(d) in ("MORNING", "AFTERNOON")

    def session_type(self, d: date) -> SessionType | None:
        return self._cache.get(d)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_calendar.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/calendar.py tests/engine/test_calendar.py
git commit -m "feat: add TradingCalendar class with cache and queries"
```

---

### Task 3: Add `early_close` to `MarketHoursConfig`

**Files:**
- Modify: `engine/config.py`
- Modify: `tests/engine/test_config.py`
- Modify: `config.yaml.example`

- [ ] **Step 1: Update the test config dict**

In `tests/engine/test_config.py`, locate the `_valid_config_dict()` helper. Update its `market_hours` block to include `early_close`:

```python
        "market_hours": {"open": "09:30", "close": "16:00", "early_close": "13:00", "tz": "America/New_York"},
```

Then update `test_load_config_returns_typed_config` to also assert the new field:

```python
    assert config.market_hours.early_close == "13:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_config.py::test_load_config_returns_typed_config -v`
Expected: FAIL — `MarketHoursConfig.__init__() got an unexpected keyword argument 'early_close'`.

- [ ] **Step 3: Add the field**

In `engine/config.py`, add `early_close: str` to the `MarketHoursConfig` dataclass:

```python
@dataclass
class MarketHoursConfig:
    open: str
    close: str
    early_close: str
    tz: str
```

- [ ] **Step 4: Run config tests to verify**

Run: `pytest tests/engine/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Update `config.yaml.example`**

Replace the `market_hours` block in `config.yaml.example` with:

```yaml
market_hours:
  open: "09:30"
  close: "16:00"
  early_close: "13:00"
  tz: "America/New_York"
```

- [ ] **Step 6: Commit**

```bash
git add engine/config.py tests/engine/test_config.py config.yaml.example
git commit -m "feat: add early_close field to MarketHoursConfig"
```

---

### Task 4: `is_market_open` and `next_open` consume the calendar

**Files:**
- Modify: `engine/market_hours.py`
- Modify: `tests/engine/test_market_hours.py`

- [ ] **Step 1: Update existing tests + add new tests**

Open `tests/engine/test_market_hours.py`. The existing tests use a `CONFIG` constant for `MarketHoursConfig` — update it to include `early_close`:

```python
CONFIG = MarketHoursConfig(open="09:30", close="16:00", early_close="13:00", tz="America/New_York")
```

The existing tests call `is_market_open(now, CONFIG)` and `next_open(now, CONFIG)` — every call needs a third argument: a calendar mock that says "every day is a trading day with WHOLE session." Add this fixture at the top of the file:

```python
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def all_days_calendar():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="WHOLE")
    return cal
```

Update every existing test to take the `all_days_calendar` fixture and pass it as the third argument to `is_market_open` / `next_open`. For example:

```python
def test_is_market_open_during_hours(all_days_calendar):
    now = datetime(2024, 1, 16, 10, 30, tzinfo=NY)
    assert is_market_open(now, CONFIG, all_days_calendar) is True
```

Apply the same pattern to all 8 existing tests.

Note: the weekend test (`test_is_market_open_on_weekend`) currently relies on the weekday check inside `is_market_open`. After this change, the weekday check is replaced by the calendar lookup. So the weekend test must use a calendar that returns False for that Saturday. Replace the existing `test_is_market_open_on_weekend` body with one that uses a holiday-style calendar:

```python
def test_is_market_open_returns_false_when_calendar_says_non_trading():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=False)
    cal.session_type = MagicMock(return_value=None)
    now = datetime(2024, 1, 13, 10, 30, tzinfo=NY)  # Saturday in this test
    assert is_market_open(now, CONFIG, cal) is False
```

Then add new tests after the existing block:

```python
def test_is_market_open_uses_early_close_on_morning_session():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="MORNING")
    # 14:00 ET on a half day — past early close (13:00) but before regular close (16:00)
    now = datetime(2024, 11, 29, 14, 0, tzinfo=NY)
    assert is_market_open(now, CONFIG, cal) is False


def test_is_market_open_open_before_early_close_on_morning_session():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="MORNING")
    # 12:00 ET on a half day — before early close
    now = datetime(2024, 11, 29, 12, 0, tzinfo=NY)
    assert is_market_open(now, CONFIG, cal) is True


def test_is_market_open_normal_close_on_whole_session():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="WHOLE")
    # 14:00 ET on a normal day — within hours
    now = datetime(2024, 1, 16, 14, 0, tzinfo=NY)
    assert is_market_open(now, CONFIG, cal) is True


def test_next_open_skips_holiday():
    # Calendar says 2024-01-17 (Wednesday) is a non-trading day; 2024-01-18 (Thursday) is a trading day
    cal = MagicMock()
    cal.is_trading_day = MagicMock(side_effect=lambda d: d.isoformat() != "2024-01-17")
    now = datetime(2024, 1, 16, 17, 0, tzinfo=NY)  # Tuesday after close
    nxt = next_open(now, CONFIG, cal)
    assert nxt.date().isoformat() == "2024-01-18"


def test_next_open_raises_when_no_trading_day_within_bound():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=False)
    now = datetime(2024, 1, 16, 17, 0, tzinfo=NY)
    with pytest.raises(RuntimeError):
        next_open(now, CONFIG, cal)
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `pytest tests/engine/test_market_hours.py -v`
Expected: FAIL — `is_market_open` and `next_open` don't accept a third argument yet.

- [ ] **Step 3: Update the implementation**

Replace the body of `engine/market_hours.py` with:

```python
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .calendar import TradingCalendar
from .config import MarketHoursConfig


_MAX_NEXT_OPEN_LOOKAHEAD_DAYS = 14


def _parse_time(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def is_market_open(
    now: datetime, config: MarketHoursConfig, calendar: TradingCalendar,
) -> bool:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    if not calendar.is_trading_day(local.date()):
        return False
    open_t = _parse_time(config.open)
    if calendar.session_type(local.date()) == "MORNING":
        close_t = _parse_time(config.early_close)
    else:
        close_t = _parse_time(config.close)
    return open_t <= local.time() < close_t


def next_open(
    now: datetime, config: MarketHoursConfig, calendar: TradingCalendar,
) -> datetime:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    open_t = _parse_time(config.open)

    candidate = local.replace(
        hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0
    )
    if local >= candidate:
        candidate = candidate + timedelta(days=1)
    for _ in range(_MAX_NEXT_OPEN_LOOKAHEAD_DAYS):
        if calendar.is_trading_day(candidate.date()):
            return candidate
        candidate = candidate + timedelta(days=1)
    raise RuntimeError(
        f"No trading day found within {_MAX_NEXT_OPEN_LOOKAHEAD_DAYS} days "
        f"of {now} — calendar may be unloaded or exhausted."
    )
```

- [ ] **Step 4: Run all market_hours tests**

Run: `pytest tests/engine/test_market_hours.py -v`
Expected: all tests pass (8 updated + 5 new = 13 minimum).

- [ ] **Step 5: Commit**

```bash
git add engine/market_hours.py tests/engine/test_market_hours.py
git commit -m "feat: market_hours honors trading calendar and half-day closes"
```

---

### Task 5: Engine takes a calendar

**Files:**
- Modify: `engine/loop.py`
- Modify: `tests/engine/test_loop.py`

- [ ] **Step 1: Update test fixtures**

In `tests/engine/test_loop.py`, locate the `deps` fixture. Add a `calendar` mock to the returned tuple. The new fixture:

```python
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
    order_update_buffer: list[dict] = []
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=[])
    store = MagicMock()
    store.proposed_trades_path = MagicMock(return_value=Path("/tmp/proposals.jsonl"))
    store.proposal_results_path = MagicMock(return_value=Path("/tmp/results.json"))
    store.recent_fills_path = MagicMock(return_value=Path("/tmp/recent_fills.json"))
    store.recent_order_updates_path = MagicMock(return_value=Path("/tmp/recent_order_updates.json"))
    store.atomic_write_text = MagicMock()
    calendar = MagicMock()
    calendar.is_trading_day = MagicMock(return_value=True)
    calendar.session_type = MagicMock(return_value="WHOLE")
    return (collector, runner, prompt_builder, account, orders,
            fill_buffer, order_update_buffer, executor, store, calendar)
```

Update `_make_config()` so the `MarketHoursConfig` it returns includes `early_close`:

```python
        market_hours=MarketHoursConfig(open="09:30", close="16:00", early_close="13:00", tz="America/New_York"),
```

Then update every test that unpacks `deps`. Find every line like:
```python
collector, runner, prompt_builder, account, orders, fill_buffer, order_update_buffer, executor, store = deps
```
and replace with:
```python
collector, runner, prompt_builder, account, orders, fill_buffer, order_update_buffer, executor, store, calendar = deps
```

Find every `Engine(...)` construction call and add `calendar=calendar,` as a kwarg.

- [ ] **Step 2: Add the new failing test**

Append to `tests/engine/test_loop.py`:

```python
async def test_tick_skips_on_non_trading_day(deps):
    (collector, runner, prompt_builder, account, orders,
     fill_buffer, order_update_buffer, executor, store, calendar) = deps
    calendar.is_trading_day = MagicMock(return_value=False)
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=store, calendar=calendar, log_writer=MagicMock(),
    )
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)

    collector.collect.assert_not_awaited()
    runner.run.assert_not_awaited()
```

- [ ] **Step 3: Run new test to verify it fails**

Run: `pytest tests/engine/test_loop.py::test_tick_skips_on_non_trading_day -v`
Expected: FAIL — `Engine.__init__` doesn't accept `calendar`.

- [ ] **Step 4: Update Engine**

In `engine/loop.py`:

1. Add `from .calendar import TradingCalendar` to imports.

2. Add `calendar: TradingCalendar` to `Engine.__init__` signature, immediately before `log_writer`. Store: `self._calendar = calendar`.

3. In `tick()`, find the existing `is_market_open` call:

```python
        if not is_market_open(now, self._config.market_hours):
            return
```

Replace with:

```python
        if not is_market_open(now, self._config.market_hours, self._calendar):
            return
```

- [ ] **Step 5: Run all engine loop tests**

Run: `pytest tests/engine/test_loop.py -v`
Expected: all tests pass (previous count + 1 new).

- [ ] **Step 6: Commit**

```bash
git add engine/loop.py tests/engine/test_loop.py
git commit -m "feat: Engine takes TradingCalendar and passes through to is_market_open"
```

---

### Task 6: Wire it up in main.py + final integration check

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update `main.py`**

Open `main.py`. Add to imports:

```python
from datetime import timedelta
from engine.calendar import TradingCalendar
```

After `MarketData` is constructed (it's created as `market_data = MarketData(conn)` inside the `async with ConnectionManager(...)` block), add:

```python
        calendar = TradingCalendar(market_data=market_data, market="US")
        today = datetime.now().date()
        await calendar.load(start=today, end=today + timedelta(days=365))
```

Place this after the four connector instances are constructed but before the collector/engine setup.

In the `Engine(...)` constructor call, add `calendar=calendar,` as a kwarg.

In the outer wait loop, find both calls to `is_market_open(now, config.market_hours)` and `next_open(now, config.market_hours)` and add `calendar` as the third argument:

```python
            if not is_market_open(now, config.market_hours, calendar):
                wakeup = next_open(now, config.market_hours, calendar)
```

- [ ] **Step 2: Verify imports resolve cleanly**

Run:
```bash
python3 -c "
from engine.config import load_config
from engine.market_hours import is_market_open
from engine.safe_orders import SafeOrders
from engine.executor import ProposalExecutor
from engine.calendar import TradingCalendar
from engine.loop import Engine
from data.store import DataStore
from data.collector import Collector
from agent.runner import AgentRunner
from agent.prompt import PromptBuilder
from connector.market_data import MarketData
from connector.orders import Orders
print('All imports OK')
"
```
Expected: `All imports OK`.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: all tests pass (previous 118 + ~13 new = ~131), no warnings.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "chore: wire TradingCalendar through main"
```
