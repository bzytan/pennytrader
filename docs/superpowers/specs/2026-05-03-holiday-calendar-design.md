# Holiday Calendar Design

## Overview

Replace the current "every weekday is a trading day" assumption with a real US equity market calendar sourced from moomoo's `request_trading_days` API. The calendar covers full closures (US holidays, weekends) and half-day early closes (post-Thanksgiving, Christmas Eve, etc.).

## Goals

- Use the broker's own calendar as the single source of truth — no third-party calendar drift
- Honor half-day early closes so the engine doesn't send orders into a closed market
- Cache the calendar at engine startup; no repeated API calls per tick
- Fail visibly at startup if the calendar can't be loaded (rather than silently trading on holidays)

## Non-Goals

- AFTERNOON-only sessions (rare in US equities; will be treated as WHOLE for v1)
- Periodic refresh during a long-running session (a 365-day load is sufficient for any realistic uptime; refresh is a future enhancement)
- Markets other than US

## Architecture

A new `TradingCalendar` class owns the in-memory mapping from `date` to session type. The `Engine` constructs and loads the calendar at startup, then passes it into the existing `is_market_open` and `next_open` helpers each tick. Those helpers gain a `calendar` parameter — the previous "weekday and within hours" logic is replaced with "in calendar and within hours, where the close time depends on the session type."

```
moomoo SDK
    │
    │ request_trading_days(market, start, end)
    ▼
MarketData.get_trading_days()  ←  new connector method
    │
    │ list[{"date": date, "type": str}]
    ▼
TradingCalendar.load()  ←  new module engine/calendar.py
    │
    │ in-memory dict: date → "WHOLE" | "MORNING" | "AFTERNOON"
    ▼
is_market_open(now, config, calendar)
next_open(now, config, calendar)
    │
    ▼
Engine.tick() / main.py wait loop
```

## Component Changes

### `connector/market_data.py`

New method:

```python
async def get_trading_days(
    self, market: str, start: date, end: date
) -> list[dict]:
    """Returns trading days in [start, end].

    Each entry: {"date": date, "type": "WHOLE" | "MORNING" | "AFTERNOON"}.
    Non-trading days are omitted from the result.
    """
```

Wraps `quote_ctx.request_trading_days(market=market, start=start_str, end=end_str)` via `run_in_executor`. The SDK returns a list of dicts with `time` (str) and `trade_date_type` (str). The wrapper converts `time` to `date` and renames the type field to `type`. Errors map to `MoomooMarketDataError`.

The `market` parameter is a string (e.g., `"US"`) that maps to `ft.TradeDateMarket.US`. The wrapper does this mapping internally so callers don't need to import the SDK enum.

### `engine/calendar.py` (new file)

```python
from datetime import date
from typing import Literal

from connector.market_data import MarketData

SessionType = Literal["WHOLE", "MORNING", "AFTERNOON"]


class TradingCalendar:
    def __init__(self, market_data: MarketData, market: str = "US") -> None: ...

    async def load(self, start: date, end: date) -> None:
        """Populate the cache by calling market_data.get_trading_days."""

    def is_trading_day(self, d: date) -> bool: ...

    def is_half_day(self, d: date) -> bool:
        """True if session_type(d) is MORNING or AFTERNOON."""

    def session_type(self, d: date) -> SessionType | None:
        """Returns the session type, or None if d is not a trading day."""
```

The cache is a single `dict[date, SessionType]` populated by `load()`. Dates outside the loaded range return `False` from `is_trading_day` and `None` from `session_type` — conservative default that prevents trading without explicit calendar coverage.

`load()` is idempotent — calling it again replaces the cache with a fresh fetch.

### `engine/config.py`

Add one field to `MarketHoursConfig`:

```python
@dataclass
class MarketHoursConfig:
    open: str
    close: str
    early_close: str
    tz: str
```

`config.yaml.example` updated:

```yaml
market_hours:
  open: "09:30"
  close: "16:00"
  early_close: "13:00"   # NEW — used on MORNING half-days
  tz: "America/New_York"
```

### `engine/market_hours.py`

Both functions gain a `calendar: TradingCalendar` parameter:

```python
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
    """Returns the next datetime when the market opens, skipping
    weekends and any non-trading days in the calendar."""
```

`next_open` walks forward day-by-day until `calendar.is_trading_day(candidate.date())` returns True, with a hard bound of 14 days (no real holiday gap is longer). If the bound is hit, raises a `RuntimeError` — this signals an exhausted or unloaded calendar and should never happen in normal operation.

The previous weekday-only check is removed — the calendar fully replaces it.

### `engine/loop.py`

Engine constructor takes a `calendar: TradingCalendar` parameter. Stored as `self._calendar`. Passed into `is_market_open` calls in `tick()`.

### `main.py`

After `MarketData` is constructed but before the engine starts:

```python
from datetime import timedelta
from engine.calendar import TradingCalendar

calendar = TradingCalendar(market_data=market_data, market="US")
today = datetime.now().date()
await calendar.load(start=today, end=today + timedelta(days=365))
```

Pass `calendar=calendar` to the `Engine` constructor.

The outer `is_market_open` / `next_open` calls in main.py's wait loop also get `calendar=calendar` passed in.

If `calendar.load()` raises, the exception propagates and the engine fails to start — desired behavior.

## Testing

All tests mock the SDK boundary; no live OpenD required.

- **`tests/connector/test_market_data.py`** — 1 new test:
  - `test_get_trading_days_returns_typed_list` — mocks `quote_ctx.request_trading_days`, verifies the returned list has `date` and `type` keys with correct values

- **`tests/engine/test_calendar.py`** — new file:
  - `test_load_populates_cache` — calls `load()` with a mocked `MarketData`, verifies subsequent queries hit the cache
  - `test_is_trading_day_returns_true_for_known_day`
  - `test_is_trading_day_returns_false_for_holiday` (date not in cache)
  - `test_is_trading_day_returns_false_for_date_outside_loaded_range`
  - `test_is_half_day_for_morning_session` returns True
  - `test_is_half_day_for_whole_session` returns False
  - `test_session_type_returns_correct_type`
  - `test_session_type_returns_none_for_non_trading_day`
  - `test_load_replaces_existing_cache` (idempotent re-load)

- **`tests/engine/test_market_hours.py`** — extend existing tests + new tests:
  - All existing tests get a `calendar` fixture that returns `is_trading_day=True, session_type="WHOLE"` for the relevant dates
  - New: `test_is_market_open_false_on_holiday` — calendar says non-trading day → False even during normal hours
  - New: `test_is_market_open_uses_early_close_on_morning_session` — afternoon (after early close) returns False on a half day
  - New: `test_is_market_open_normal_close_on_whole_session` — afternoon before normal close returns True on a full day
  - New: `test_next_open_skips_holiday` — calendar with a holiday in the path → next_open returns the day after

- **`tests/engine/test_loop.py`** — extend deps fixture with a `calendar` mock; one new test `test_tick_skips_on_non_trading_day` (calendar says today is not a trading day → no collector or runner calls)

- **Test counts:** ~10 new tests on top of 118.

## Error Handling

| Failure | Handling |
|---|---|
| `request_trading_days` returns RET_ERROR | Wrapped as `MoomooMarketDataError` by the connector method. Propagates from `calendar.load()` and prevents engine start. |
| Calendar queried for date outside loaded range | Returns `False` from `is_trading_day` (conservative — treats unknown dates as non-trading). Engine effectively halts trading until calendar is reloaded. |
| Engine runs longer than 365 days without restart | Cache becomes stale, engine effectively stops trading. Acceptable for v1; periodic refresh is a future improvement. |

## Out of Scope

- Periodic calendar refresh during a long session
- Markets other than US
- AFTERNOON-only sessions (treated as WHOLE; revisit if a US session ever uses this)
- Dynamic close-time discovery (close time per half-day type is from config; in practice US half-days end at 1pm ET universally)
