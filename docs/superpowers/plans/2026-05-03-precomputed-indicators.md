# Pre-computed Indicators + Memory-Contract Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pre-compute six table-stakes technical indicators (VWAP, SMA(5/20), volume-relative, session high/low, % from open) in the data collector and surface them via the existing per-symbol quote file. Plus a one-paragraph addition to the agent system prompt making the stateless-tick memory contract explicit.

**Architecture:** A new `data/indicators.py` module exposes pure functions that compute each indicator from a list of bar dicts plus the simulated `now`. The collector calls the new module after fetching the quote and history bars and merges the result into the quote dict before atomic-writing. No engine, agent, or broker changes; the agent reads the quote file as before but now sees indicator values alongside the price.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio. No new dependencies.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `data/indicators.py` | Create | `compute_indicators(bars, now)` returning a dict of six fields |
| `tests/data/test_indicators.py` | Create | Pure-function tests for each indicator + edge cases |
| `data/collector.py` | Modify | `_write_quote(symbol, now)` computes indicators and merges into quote dict |
| `tests/data/test_collector.py` | Modify | Verify `indicators` key appears in quote file with correct values |
| `agent/prompt.py` | Modify | Append memory-contract paragraph to `_SYSTEM_PROMPT` |

---

### Task 1: Indicator pure functions

**Files:**
- Create: `data/indicators.py`
- Create: `tests/data/test_indicators.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/data/test_indicators.py`:

```python
from datetime import datetime

from data.indicators import compute_indicators


def _bar(time, open_, close, high, low, volume):
    return {"time": time, "open": open_, "close": close,
            "high": high, "low": low, "volume": volume}


# --- SMA tests ---

def test_sma_5_returns_none_when_fewer_than_5_bars():
    bars = [_bar("2026-04-27 09:30:00", 100, 101, 101, 99, 1000)] * 4
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 34))
    assert result["sma_5"] is None


def test_sma_5_returns_average_of_last_5_closes():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    bars = [_bar(f"2026-04-27 09:3{i}:00", 100, c, c, c, 1000)
            for i, c in enumerate(closes)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 35))
    assert result["sma_5"] == 102.0  # (100+101+102+103+104)/5


def test_sma_5_uses_only_last_5_when_more_bars_present():
    closes = list(range(1, 11))  # [1,2,...,10]
    bars = [_bar(f"2026-04-27 09:{i:02d}:00", 100, float(c), c, c, 1000)
            for i, c in enumerate(closes, start=30)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 10, 0))
    # last 5 closes are 6,7,8,9,10 → avg = 8.0
    assert result["sma_5"] == 8.0


def test_sma_20_returns_none_when_fewer_than_20_bars():
    bars = [_bar(f"2026-04-27 09:{i:02d}:00", 100, 100, 100, 100, 1000)
            for i in range(30, 49)]  # 19 bars
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 49))
    assert result["sma_20"] is None


def test_sma_20_returns_correct_value_on_exactly_20_bars():
    closes = [float(c) for c in range(1, 21)]
    bars = [_bar(f"2026-04-27 09:{i:02d}:00", 100, c, c, c, 1000)
            for i, c in zip(range(30, 50), closes)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 50))
    # avg of 1..20 = 10.5
    assert result["sma_20"] == 10.5


# --- VWAP tests ---

def test_vwap_returns_none_when_no_today_bars():
    bars = [_bar("2026-04-26 09:30:00", 100, 101, 102, 99, 1000)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 30))
    assert result["vwap"] is None


def test_vwap_computed_on_today_bars_only():
    # Yesterday's bars should be excluded
    bars = [
        _bar("2026-04-26 14:00:00", 50, 50, 50, 50, 99999),  # excluded
        _bar("2026-04-27 09:30:00", 100, 100, 100, 100, 1000),
        _bar("2026-04-27 09:31:00", 100, 110, 110, 100, 2000),
    ]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 32))
    # typical price uses (high+low+close)/3 (or close if simpler)
    # Using close-weighted VWAP: (100*1000 + 110*2000) / (1000+2000) = 320000/3000 = 106.667
    assert abs(result["vwap"] - 106.6667) < 0.01


def test_vwap_returns_none_when_total_volume_zero():
    bars = [
        _bar("2026-04-27 09:30:00", 100, 101, 101, 100, 0),
        _bar("2026-04-27 09:31:00", 100, 102, 102, 100, 0),
    ]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 32))
    assert result["vwap"] is None


# --- Volume relative tests ---

def test_vol_relative_returns_none_when_fewer_than_20_bars():
    bars = [_bar(f"2026-04-27 09:{i:02d}:00", 100, 100, 100, 100, 1000)
            for i in range(30, 35)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 35))
    assert result["vol_relative"] is None


def test_vol_relative_computed_against_20_bar_average():
    # 19 bars at volume 1000, then 1 bar at volume 2000 = 20 bars
    # 20-bar avg = (19*1000 + 2000)/20 = 1050
    # last bar = 2000
    # vol_relative = 2000/1050 ≈ 1.9047
    bars = [_bar(f"2026-04-27 09:{i:02d}:00", 100, 100, 100, 100, 1000)
            for i in range(30, 49)]
    bars.append(_bar("2026-04-27 09:49:00", 100, 100, 100, 100, 2000))
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 50))
    assert abs(result["vol_relative"] - (2000 / 1050)) < 0.001


def test_vol_relative_returns_none_when_average_volume_zero():
    bars = [_bar(f"2026-04-27 09:{i:02d}:00", 100, 100, 100, 100, 0)
            for i in range(30, 50)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 50))
    assert result["vol_relative"] is None


# --- Session high / low tests ---

def test_session_high_low_uses_today_only():
    bars = [
        _bar("2026-04-26 14:00:00", 100, 100, 200, 50, 1000),  # excluded
        _bar("2026-04-27 09:30:00", 100, 105, 110, 95, 1000),
        _bar("2026-04-27 09:31:00", 105, 108, 115, 100, 1000),
    ]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 32))
    assert result["session_high"] == 115.0
    assert result["session_low"] == 95.0


def test_session_high_low_return_none_when_no_today_bars():
    bars = [_bar("2026-04-26 14:00:00", 100, 100, 200, 50, 1000)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 30))
    assert result["session_high"] is None
    assert result["session_low"] is None


# --- pct from open tests ---

def test_pct_from_open_uses_today_open():
    bars = [
        _bar("2026-04-26 14:00:00", 50, 50, 50, 50, 1000),    # excluded
        _bar("2026-04-27 09:30:00", 100, 102, 103, 99, 1000),
        _bar("2026-04-27 09:31:00", 102, 105, 106, 102, 1000),
    ]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 32))
    # open today = 100, last close = 105 → +5%
    assert abs(result["pct_from_open"] - 5.0) < 0.001


def test_pct_from_open_returns_none_when_no_today_bars():
    bars = [_bar("2026-04-26 14:00:00", 100, 100, 100, 100, 1000)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 30))
    assert result["pct_from_open"] is None


# --- All-fields integration ---

def test_compute_indicators_returns_all_six_keys():
    bars = [_bar("2026-04-27 09:30:00", 100, 101, 102, 99, 1000)]
    result = compute_indicators(bars, datetime(2026, 4, 27, 9, 31))
    for key in ("vwap", "sma_5", "sma_20", "vol_relative",
                "session_high", "session_low", "pct_from_open"):
        assert key in result, f"missing {key}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/data/test_indicators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.indicators'`.

- [ ] **Step 3: Write the implementation**

Create `data/indicators.py`:

```python
from datetime import date, datetime
from typing import Optional


def compute_indicators(bars: list[dict], now: datetime) -> dict:
    """Compute the table-stakes indicator set from a bar series.

    bars: list sorted ascending by time. Each row has keys
        time (str or datetime), open, close, high, low, volume.
    now: simulated or wall-clock time. Used to determine 'today'.

    Returns a dict with six keys; each value is float or None.
    None signals insufficient data for that specific indicator.
    """
    today = now.date() if isinstance(now, datetime) else now
    today_bars = [b for b in bars if _bar_date(b) == today]
    return {
        "vwap": _vwap(today_bars),
        "sma_5": _sma(bars, 5),
        "sma_20": _sma(bars, 20),
        "vol_relative": _vol_relative(bars, 20),
        "session_high": _session_extreme(today_bars, "high", max),
        "session_low": _session_extreme(today_bars, "low", min),
        "pct_from_open": _pct_from_open(today_bars),
    }


def _bar_date(bar: dict) -> Optional[date]:
    t = bar["time"]
    if isinstance(t, datetime):
        return t.date()
    if isinstance(t, date):
        return t
    s = str(t)
    # accepts "YYYY-MM-DD HH:MM:SS" or ISO; both have date in first 10 chars
    return date.fromisoformat(s[:10])


def _sma(bars: list[dict], window: int) -> Optional[float]:
    if len(bars) < window:
        return None
    closes = [float(b["close"]) for b in bars[-window:]]
    return sum(closes) / window


def _vwap(today_bars: list[dict]) -> Optional[float]:
    if not today_bars:
        return None
    total_vol = sum(float(b["volume"]) for b in today_bars)
    if total_vol <= 0:
        return None
    weighted = sum(float(b["close"]) * float(b["volume"]) for b in today_bars)
    return weighted / total_vol


def _vol_relative(bars: list[dict], window: int) -> Optional[float]:
    if len(bars) < window:
        return None
    last_n = bars[-window:]
    total = sum(float(b["volume"]) for b in last_n)
    if total <= 0:
        return None
    avg = total / window
    last_vol = float(bars[-1]["volume"])
    return last_vol / avg


def _session_extreme(today_bars: list[dict], field: str, fn) -> Optional[float]:
    if not today_bars:
        return None
    return float(fn(float(b[field]) for b in today_bars))


def _pct_from_open(today_bars: list[dict]) -> Optional[float]:
    if not today_bars:
        return None
    open_price = float(today_bars[0]["open"])
    if open_price == 0:
        return None
    last_close = float(today_bars[-1]["close"])
    return (last_close - open_price) / open_price * 100
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/data/test_indicators.py -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add data/indicators.py tests/data/test_indicators.py
git commit -m "feat: add data/indicators with table-stakes technical signals"
```

---

### Task 2: Collector merges indicators into quote file

**Files:**
- Modify: `data/collector.py`
- Modify: `tests/data/test_collector.py`

- [ ] **Step 1: Read the current collector to understand the structure**

Open `data/collector.py` and review the `_write_quote(self, symbol)` method and how `collect()` calls it. The current signature is `_write_quote(self, symbol)` — we need to add `now: datetime` so the indicator function can identify today's bars.

- [ ] **Step 2: Write the failing tests**

Append to `tests/data/test_collector.py`:

```python
async def test_collect_merges_indicators_into_quote_file(
    store, market_data, options, account, orders, history_config, options_config,
):
    # Override get_price_history to return a deterministic series
    today_iso = "2024-01-16"
    bars = []
    for i in range(20):
        bars.append({
            "time": f"{today_iso} 09:{30 + i:02d}:00",
            "open": 100.0, "close": 100.0 + i,
            "high": 100.0 + i + 1, "low": 100.0 - 1,
            "volume": 1000, "turnover": 100000.0,
        })
    market_data.get_price_history = AsyncMock(return_value=bars)

    collector = Collector(
        store=store, market_data=market_data, options=options,
        account=account, orders=orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=lambda symbol, n: [date(2024, 1, 19)],
    )
    await collector.collect(["AAPL"], now=datetime(2024, 1, 16, 9, 50))

    quote = json.loads(store.quote_path("AAPL").read_text())
    assert "indicators" in quote
    ind = quote["indicators"]
    assert ind["sma_5"] == sum([115, 116, 117, 118, 119]) / 5  # last 5 closes
    assert ind["sma_20"] == sum(range(100, 120)) / 20  # avg of 100..119
    assert ind["session_high"] == 100.0 + 19 + 1  # last bar's high
    assert ind["session_low"] == 99.0  # constant low across bars


async def test_collect_indicators_empty_dict_when_compute_raises(
    store, market_data, options, account, orders, history_config, options_config,
    monkeypatch,
):
    # Force compute_indicators to raise — verify indicators field is {}
    import data.collector as collector_module
    def raising(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(collector_module, "compute_indicators", raising)

    collector = Collector(
        store=store, market_data=market_data, options=options,
        account=account, orders=orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=lambda symbol, n: [date(2024, 1, 19)],
    )
    await collector.collect(["AAPL"], now=datetime(2024, 1, 16, 9, 50))

    quote = json.loads(store.quote_path("AAPL").read_text())
    assert quote["indicators"] == {}
```

Note: the existing test fixtures (`store`, `market_data`, etc.) and imports (`AsyncMock`, `datetime`, `date`, `json`) should already be at the top of the file. Verify and add any missing imports (`from datetime import datetime`).

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/data/test_collector.py::test_collect_merges_indicators_into_quote_file tests/data/test_collector.py::test_collect_indicators_empty_dict_when_compute_raises -v`
Expected: FAIL — `_write_quote` doesn't merge indicators yet.

- [ ] **Step 4: Update the collector**

In `data/collector.py`:

Add the import at the top:

```python
from data.indicators import compute_indicators
```

Replace the `_write_quote` and `collect` methods with:

```python
    async def collect(self, watchlist: list[str], now: datetime) -> None:
        for symbol in watchlist:
            await self._write_quote(symbol, now=now)
            await self._write_history(symbol, now=now)
            await self._write_options(symbol)
        await self._write_account()

    async def _write_quote(self, symbol: str, now: datetime) -> None:
        quote = await self._market_data.get_quote(symbol)

        end = now
        start = end - timedelta(hours=self._history_config.lookback_hours)
        ktype = _interval_to_ktype(self._history_config.interval)
        bars = await self._market_data.get_price_history(
            symbol, start.date(), end.date(), ktype,
        )
        try:
            quote["indicators"] = compute_indicators(bars, now)
        except Exception:
            # Defensive: indicator math failure must not break the tick.
            quote["indicators"] = {}

        self._store.atomic_write_text(
            self._store.quote_path(symbol), json.dumps(quote, indent=2)
        )
```

The `_write_history` method already takes `now`; no change there. The `collect` method already takes `now` (from the previous simulated-time fix); we're just adding the same kwarg to the `_write_quote` call.

- [ ] **Step 5: Run all collector tests**

Run: `pytest tests/data/test_collector.py -v`
Expected: all tests pass (existing 5 + 2 new = 7 minimum).

- [ ] **Step 6: Run full suite to catch any regression**

Run: `pytest tests/ -q 2>&1 | tail -3`
Expected: 211 + 2 new + 14 from Task 1 = 227 passed, no failures.

- [ ] **Step 7: Commit**

```bash
git add data/collector.py tests/data/test_collector.py
git commit -m "feat: collector merges indicators into quote file"
```

---

### Task 3: Memory-contract paragraph in system prompt

**Files:**
- Modify: `agent/prompt.py`

- [ ] **Step 1: Read the current system prompt**

Open `agent/prompt.py` and locate the `_SYSTEM_PROMPT` constant. Find the closing `Important:` bullet list (last block before the `"""` end-of-string). The new paragraph appends after the existing bullets.

- [ ] **Step 2: Append the memory-contract paragraph**

In `agent/prompt.py`, find this section at the end of `_SYSTEM_PROMPT`:

```python
Important:
- Doing nothing is often the right decision. Do not feel obligated to trade.
- Each invocation is stateless — you have no memory of prior ticks. State lives in
  the broker (positions, orders, fills) and the data files.
- Per-trade size cap is enforced by the system. The current dollar limit is in
  `max_per_trade_usd` in the state JSON. Compute notional = qty × price (× contract_size
  for options) and keep it under that cap or your proposal will be rejected.
- Your reasoning, scripts you run, and proposals are all logged for later review."""
```

Replace it with:

```python
Important:
- Doing nothing is often the right decision. Do not feel obligated to trade.
- Each invocation is stateless — you have no memory of prior ticks. State lives in
  the broker (positions, orders, fills) and the data files.
- Per-trade size cap is enforced by the system. The current dollar limit is in
  `max_per_trade_usd` in the state JSON. Compute notional = qty × price (× contract_size
  for options) and keep it under that cap or your proposal will be rejected.
- Your reasoning, scripts you run, and proposals are all logged for later review.

Memory contract: the system has no memory of your reasoning between ticks. If you
intend to commit to an exit at a specific price, place a stop or limit order — broker
state persists, your narrative does not. Plans expressed only in your reasoning are
forgotten the moment you exit. Encode commitments as orders."""
```

- [ ] **Step 3: Run prompt tests to verify nothing broke**

Run: `pytest tests/agent/test_prompt.py -v`
Expected: all 7 existing tests pass. None of them assert exact wording on this paragraph.

- [ ] **Step 4: Run full suite**

Run: `pytest tests/ -q 2>&1 | tail -3`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add agent/prompt.py
git commit -m "feat: add memory contract paragraph to agent system prompt"
```

---

### Task 4: End-to-end smoke verification

**Files:** None — verification only.

- [ ] **Step 1: Confirm imports resolve**

```bash
python3 -c "
from data.indicators import compute_indicators
from data.collector import Collector
print('All imports OK')
"
```
Expected: `All imports OK`.

- [ ] **Step 2: Quick functional smoke**

```bash
python3 -c "
from datetime import datetime
from data.indicators import compute_indicators
bars = [
    {'time': '2024-01-16 09:30:00', 'open': 100.0, 'close': 101.0,
     'high': 102.0, 'low': 99.0, 'volume': 1000},
    {'time': '2024-01-16 09:31:00', 'open': 101.0, 'close': 103.0,
     'high': 104.0, 'low': 100.0, 'volume': 2000},
]
result = compute_indicators(bars, datetime(2024, 1, 16, 9, 32))
print(result)
"
```
Expected: a dict with `sma_5`, `sma_20`, `vol_relative` as `None` (insufficient data) and `vwap`, `session_high`, `session_low`, `pct_from_open` populated with reasonable values.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: all tests pass — 211 baseline + 14 indicator tests + 2 collector tests = 227.
