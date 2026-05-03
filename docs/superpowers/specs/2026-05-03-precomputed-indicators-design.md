# Pre-computed Indicators + Memory-Contract Prompt Design

## Overview

Two complementary improvements bundled because they share a goal: reduce per-tick agent latency while improving decision quality.

1. **Pre-computed indicators** — compute a small set of table-stakes technical indicators in the collector and surface them via the existing quote file. The agent stops re-deriving VWAP, SMAs, and volume averages from raw bars on every tick.
2. **Memory-contract prompt addition** — make the stateless-tick contract explicit so the agent encodes conditional plans (e.g., "exit at $158") as broker orders rather than narrative that gets forgotten.

## Goals

- Cut ~30-40 seconds off the average tick latency by removing redundant pandas-script work in the agent subprocess
- Give the agent a consistent baseline of derived metrics each tick, regardless of whether it chooses to write its own analysis script
- Push the agent toward concrete, persistable expressions of intent (orders) rather than narrative that doesn't survive between ticks

## Non-Goals

- Larger indicator sets (RSI, MACD, ATR, multi-timeframe analysis) — start with table stakes, expand based on real failure modes
- Indicators on options contracts — underlying stock indicators only for v1
- Adding tactical scratch-pad memory between ticks — this is intentionally deferred until live shakedown reveals specific failure modes

## Indicator Set

Six fields, derived from bars the collector already fetches:

| Field | Definition | Returns `None` when |
|---|---|---|
| `vwap` | session-cumulative volume-weighted average price (today's bars only) | no bars from today's date OR total session volume is 0 |
| `sma_5` | simple moving average of the last 5 bars' close prices | fewer than 5 bars available |
| `sma_20` | simple moving average of the last 20 bars' close prices | fewer than 20 bars available |
| `vol_relative` | last bar volume / 20-bar average volume | fewer than 20 bars OR average volume is 0 |
| `session_high` | high price so far today | no bars from today's date |
| `session_low` | low price so far today | no bars from today's date |
| `pct_from_open` | `(last_close - today_open) / today_open * 100` | no bars from today's date OR today's open is 0 |

All values either a `float` or `None`. No silent fallbacks, no half-truth values computed on insufficient data.

## Component Designs

### `data/indicators.py` (new module)

Pure functions, no IO, no mutation. Each takes the full bar list plus the simulated `now` and returns a single value or `None`.

```python
from datetime import datetime
from typing import Optional


def compute_indicators(bars: list[dict], now: datetime) -> dict:
    """Returns the full indicator dict. Each field is float or None.

    bars is sorted ascending by time. Each row is a dict with keys
    'time' (str or datetime), 'open', 'close', 'high', 'low', 'volume'.
    """
    return {
        "vwap": _vwap(bars, now),
        "sma_5": _sma(bars, 5),
        "sma_20": _sma(bars, 20),
        "vol_relative": _vol_relative(bars, 20),
        "session_high": _session_high(bars, now),
        "session_low": _session_low(bars, now),
        "pct_from_open": _pct_from_open(bars, now),
    }


def _sma(bars: list[dict], window: int) -> Optional[float]: ...
def _vwap(bars: list[dict], now: datetime) -> Optional[float]: ...
def _vol_relative(bars: list[dict], window: int) -> Optional[float]: ...
def _session_high(bars: list[dict], now: datetime) -> Optional[float]: ...
def _session_low(bars: list[dict], now: datetime) -> Optional[float]: ...
def _pct_from_open(bars: list[dict], now: datetime) -> Optional[float]: ...
```

Internal helpers parse the `time` field (which may be string or datetime depending on source — backtest cache stores strings, live SDK returns either) using a permissive parser. "Today's bars" means bars whose date matches `now.date()`.

### `data/collector.py` — extended `_write_quote`

```python
async def _write_quote(self, symbol: str, now: datetime) -> None:
    quote = await self._market_data.get_quote(symbol)

    # Compute indicators from the same bars the history writer will use
    end = now
    start = end - timedelta(hours=self._history_config.lookback_hours)
    ktype = _interval_to_ktype(self._history_config.interval)
    bars = await self._market_data.get_price_history(
        symbol, start.date(), end.date(), ktype,
    )
    try:
        quote["indicators"] = compute_indicators(bars, now)
    except Exception as exc:
        # Defensive: indicator math failure must not break the tick
        quote["indicators"] = {}
        # Optional: log via a hook if collector grows a logger; for v1, just continue

    self._store.atomic_write_text(
        self._store.quote_path(symbol), json.dumps(quote, indent=2)
    )
```

`_write_quote` gains a `now` parameter, mirroring `_write_history`. The collector's `collect()` already takes `now` (from the simulated-time fix), so threading is mechanical.

A note on efficiency: this calls `get_price_history` twice per symbol per tick (once in `_write_quote` for indicators, once in `_write_history` for the CSV). For backtests that's a cache hit both times so cost is microseconds. For live trading it's two SDK calls. v1 accepts this; if it becomes a problem, the future fix is to fetch once in `collect()` and pass the bars into both writers.

### `agent/prompt.py` — system prompt addition

One paragraph appended to the existing `_SYSTEM_PROMPT`, after the existing "Important" bullets:

```
Memory contract: the system has no memory of your reasoning between ticks.
If you intend to commit to an exit at a specific price, place a stop or limit
order — broker state persists, your narrative does not. Plans expressed only
in your reasoning are forgotten the moment you exit. Encode commitments as
orders.
```

No structural prompt changes, no new state fields, no new file paths.

## Data Flow

Per tick (no architectural change to engine):

```
Engine.tick(now)
  └─ Collector.collect(watchlist, now)
       for each symbol:
         ├─ MarketData.get_quote(symbol)
         ├─ MarketData.get_price_history(symbol, ...)   ← bars
         ├─ indicators.compute_indicators(bars, now)    ← NEW
         ├─ merge indicators into quote dict
         └─ atomic write quote_<symbol>.json (now with indicators)
       ├─ write history CSV (unchanged)
       └─ write account / options (unchanged)
  └─ invoke agent (now reads quote files that include indicators)
```

## Error Handling

| Failure | Handling |
|---|---|
| `get_price_history` raises | Existing collector behavior — wraps via `collector_error` event, tick aborts. No change. |
| `compute_indicators` raises (defensive — pure functions shouldn't, but) | Catch, set `quote["indicators"] = {}`, continue writing the file. Agent sees missing indicators rather than a failed tick. |
| Insufficient bars for a specific indicator | Function returns `None` for that field. Other indicators with sufficient data still populate. |
| Zero-volume edge cases (degenerate VWAP / vol_relative) | Functions return `None` rather than raising or producing NaN. |

## Testing

- **`tests/data/test_indicators.py`** — new file, ~12 tests:
  - SMA on exactly N bars (correct value)
  - SMA on fewer than N bars (returns None)
  - SMA on more than N bars (uses last N only)
  - VWAP on a known series with multiple bars from today
  - VWAP returns None when no today bars
  - VWAP returns None when total session volume is 0
  - Volume relative on a known series
  - Volume relative returns None when avg volume is 0
  - Session high/low correctly windowed to today's date only
  - Session high/low return None when no today bars
  - pct_from_open correctly uses first today bar's open
  - pct_from_open returns None when no today bars
- **`tests/data/test_collector.py`** — extend existing tests:
  - Quote file contains `indicators` key after `collect()`
  - Indicators merged correctly (verify a couple of computed values from a fixed mock dataset where the bars deterministically produce known SMA / VWAP values)
  - Indicators set to `{}` when computation hypothetically raises (mock the function)
- **`tests/agent/test_prompt.py`** — no new test required; existing tests don't lock in exact wording. The new paragraph just gets appended to `_SYSTEM_PROMPT`.

Estimated ~14 new tests on top of the existing 211.

## Out of Scope (Deliberate)

- Indicator sets beyond the table-stakes six (RSI, MACD, ATR, breakout flags, etc.) — wait for live evidence
- Indicators on options contracts — underlying only
- Multi-timeframe (e.g., daily SMA over the 1m series)
- Surfacing indicators in the inline state JSON — quote file is sufficient
- Caching indicator values across ticks (re-computed each tick from the same cached bars; cheap)
- Tactical scratch pad / agent memory — explicitly deferred per session-discussion until live failure modes emerge
- Single-fetch optimization for `get_price_history` (called twice per symbol per tick) — premature

## Notes

The memory-contract prompt change is small enough that it could land independently as a one-line commit. It's bundled here because the brainstorming session covered both, and they're conceptually related: both are about giving the agent the right inputs and the right rules so per-tick reasoning is faster and produces durable outcomes.
