# Backtest Harness Design

## Overview

Build a backtest harness that lets the autonomous trading agent run against historical market data exactly as it would against the live broker. Produces a self-contained run artifact (trades, equity curve, performance metrics, dream summaries, learnings) that the operator can review. Optionally, the resulting learnings can be promoted into the live system to give the live agent a head start.

## Goals

- **Research mode**: evaluate hypothetical strategies against history, throw away the output
- **Training mode**: produce a body of learnings the live agent inherits at startup, then refines via live dreaming
- Reuse the existing engine, agent, dream, analytics, and prompt code unchanged
- Configurable simulation cadences (heartbeat, dream frequency) so backtests over long windows finish in reasonable time
- Bar-aware order matching that's honest about look-ahead (proposals on tick T match against bar T+1's range)
- Local cache of historical data so repeated backtests don't re-hit moomoo

## Non-Goals

- Tick-level simulation (moomoo doesn't expose historical tick data)
- Backtesting options (moomoo doesn't expose historical options chain data)
- Slippage modeling beyond bar-aware fills
- Partial fills, multi-account portfolios, scheduled backtest runs

## Architecture

The key insight is **boundary reuse**: the existing Engine, agent, dream, analytics, and prompt code consume the connector's `MarketData`, `Account`, `Orders` interfaces — they have no idea whether those interfaces talk to a live broker or a simulator. The harness implements those same interfaces from cached historical data and a synthetic broker, plus a clock abstraction. Almost no production code changes.

```
┌──────────────────────────────────────────────────────────────────┐
│           Existing engine/agent/dream/analytics                   │
│  (unchanged — these consume connector interfaces only)            │
└──────────────────────┬───────────────────────────────────────────┘
                       │ same interfaces
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌──────────────────┐          ┌──────────────────┐
│ Live connector   │          │ Backtest harness │
│ (existing)       │          │ (new)            │
│                  │          │                  │
│ ConnectionMgr    │          │ BacktestBroker   │
│ MarketData       │          │  ├ MarketData    │
│ Account          │          │  ├ Account       │
│ Orders           │          │  └ Orders        │
│                  │          │                  │
│ ↓                │          │ ↓                │
│ moomoo OpenD     │          │ Cached history + │
│                  │          │ synthetic state  │
└──────────────────┘          └──────────────────┘
```

## Realism

- **Bar-aware fills.** Limit BUY fills when the bar's low ≤ limit price; limit SELL fills when the bar's high ≥ limit price; both at the limit price exactly. Market orders fill at the next bar's open (avoids look-ahead bias).
- **Resolution.** Configurable bar size; default **1-minute bars**. Coarser sizes available (5m, 15m, 30m, 1h, daily) for faster long-window runs at the cost of intraday fidelity.
- **Quote synthesis.** `get_quote(symbol)` returns the most recent bar's close as `last_price`, with synthetic bid/ask = close ± $0.01. Sufficient for an agent operating on bar-resolution data.
- **No slippage**, **no partial fills**, **no order book depth modeling**. These are honest simplifications, not silent ones — documented and noted in the run manifest.

## Cadence

Backtests use separate cadence settings from live, defaulting to faster-for-throughput rates:

| Setting | Live default | Backtest default |
|---|---|---|
| Heartbeat | 60 seconds | 5 simulated minutes |
| Dreams | Daily | Every 7 simulated days |
| Final consolidation dream | n/a | Always, at end of run |

Both backtest cadences are CLI-configurable per run. Same heartbeat as live (60s) is allowed but very slow.

A 1-month backtest at 5-minute heartbeat with weekly dreams = roughly 2,000 ticks + 4 dreams. At ~10 seconds per Claude invocation that's ~6 hours. A 1-year backtest at 60-minute heartbeat = ~1,650 ticks + 52 dreams = roughly 5 hours.

## Project Structure

```
pennytrader/
├── backtest/
│   ├── __init__.py
│   ├── cache.py             # HistoricalDataCache — local parquet/sqlite store
│   ├── clock.py             # SimulatedClock
│   ├── broker.py            # BacktestBroker (implements connector interfaces)
│   ├── matcher.py           # OrderMatcher — bar-aware fill simulation
│   ├── runner.py            # BacktestRunner — replay loop
│   ├── promote.py           # promote-learnings command
│   ├── cli.py               # python -m backtest entry point
│   └── __main__.py          # delegates to cli.py
├── tests/
│   └── backtest/
│       ├── test_cache.py
│       ├── test_clock.py
│       ├── test_broker.py
│       ├── test_matcher.py
│       ├── test_runner.py
│       └── test_promote.py
```

Runtime artifacts:

```
.trading_data/
├── historical_cache/             # cached bars (shared across backtest runs)
│   ├── AAPL_1m.parquet
│   └── SPY_1m.parquet
└── backtests/
    └── 2026-05-04T22-15-00_aapl-spy-jan/
        ├── trades.jsonl
        ├── equity_curve.jsonl
        ├── performance.json
        ├── learnings/learnings.jsonl
        ├── dreams/YYYY-MM-DD.md
        ├── log/decisions-YYYY-MM-DD.jsonl
        └── manifest.json         # config used for this run + summary stats
```

Each backtest run is a self-contained directory under `.trading_data/backtests/`. Live trading writes to `.trading_data/` directly; backtests write to a per-run subdirectory. Same file shapes, different root.

## Component Designs

### `backtest/cache.py` — HistoricalDataCache

Stores historical bars locally as parquet files keyed by `<symbol>_<interval>.parquet`. Reuses the live `MarketData.get_price_history` to populate, then operates from disk thereafter.

```python
class HistoricalDataCache:
    def __init__(self, cache_dir: Path) -> None: ...

    async def ensure_range(
        self, market_data: MarketData, symbol: str, interval: str,
        start: date, end: date,
    ) -> None:
        """Idempotent. Checks the cache for existing bars in [start, end].
        Fetches any gaps from market_data. Raises MoomooMarketDataError if
        the broker can't supply the requested range (rate limit, subscription
        window exhausted)."""

    def load_bars(
        self, symbol: str, interval: str, start: date, end: date,
    ) -> pd.DataFrame:
        """Returns cached bars in [start, end]. Raises ValueError if any
        date in range is missing from the cache (call ensure_range first)."""
```

Smart fetching: cache stores per-symbol date ranges. If the requested range overlaps existing data, only the gaps are fetched.

### `backtest/clock.py` — SimulatedClock

```python
class SimulatedClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta
```

The Engine and main.py currently call `datetime.now()` directly in two places (the outer wait loop in main.py, and `tick(now=now)` accepts an explicit `now`). The harness drives the simulated clock and passes its `now()` value through the existing `now=` parameters.

The only production-code change required: extract the wall-clock `datetime.now().astimezone()` call from main.py into a single function that the backtest can override. This is a one-line change.

### `backtest/broker.py` — BacktestBroker

The largest piece. Composes the four connector interfaces from cached data + simulated state:

```python
class BacktestBroker:
    def __init__(
        self, cache: HistoricalDataCache, clock: SimulatedClock,
        watchlist: list[str], interval: str,
        starting_cash: float,
    ) -> None: ...

    @property
    def market_data(self) -> "BacktestMarketData": ...

    @property
    def account(self) -> "BacktestAccount": ...

    @property
    def orders(self) -> "BacktestOrders": ...

    def process_bar(self, bar_time: datetime) -> None:
        """Called by the runner after each clock advance. Delegates to
        OrderMatcher to fill any pending orders that the latest bar
        crossed; fires fill and order-update callbacks."""
```

Internally maintains:
- `cash: float` — synthetic balance
- `positions: dict[str, Position]` — current holdings (symbol → qty + cost basis)
- `pending_orders: list[Order]` — limit orders waiting to match against future bars
- `filled_orders: list[Order]` — historical fills (served back via `get_orders(FILLED)`)
- `fill_callbacks: list[Callable[[dict], None]]` — subscribers from `subscribe_fills`
- `order_update_callbacks: list[Callable[[dict], None]]` — subscribers from `subscribe_order_updates`

Surface (matches existing connector interfaces 1:1):

`BacktestMarketData`:
- `get_quote(symbol)` — most recent bar's close as `last_price`; synthetic bid/ask = close ± $0.01; volume from bar
- `get_price_history(symbol, start, end, interval)` — reads from cache, returns same dict shape as live
- `get_option_chain(symbol, expiry)` — raises `MoomooMarketDataError("backtest mode: options not supported")`
- `subscribe_quotes(symbol, callback)` — no-op (callbacks unused in backtest)
- `get_trading_days(market, start, end)` — derives from cache: a date is a trading day if any symbol has bars on it. `type` is always `"WHOLE"` (half-days not modeled in v1 backtests).

`BacktestAccount`:
- `get_positions()` — returns `[{"symbol": ..., "qty": ..., "cost_price": ..., "current_price": ..., "market_value": ..., "unrealized_pl": ..., ...}]` from synthetic state
- `get_balance()` — `total_assets = cash + sum(market_values)`
- `get_account_info()` — `{"account_id": "BACKTEST", "currency": "USD", "environment": "backtest"}`

`BacktestOrders`:
- `place_order(spec)` — rejects options proposals with `MoomooOrderError("backtest mode: stock-only")`; queues a pending order; returns synthetic `order_id` like `"BT-0001"`
- `cancel_order(order_id)` — removes from pending
- `modify_order(order_id, qty, price)` — updates pending order
- `get_orders(status)` — filters internal state by `OrderStatus`
- `subscribe_fills(callback)` — appends to `fill_callbacks`
- `subscribe_order_updates(callback)` — appends to `order_update_callbacks`

### `backtest/matcher.py` — OrderMatcher

Bar-aware fill simulation. The timing model:

- At simulated tick `T`, the agent reads market data through the bar **ending at `T`** (no look-ahead) and submits proposals.
- At the next tick `T + heartbeat`, before invoking the agent again, the runner asks the broker to process the bar that completed between `T` and `T + heartbeat`. The matcher walks pending orders submitted at `T` (or earlier) and fills any whose price crossed that bar's range.

| Order type | Fill condition (against the bar following the order) | Fill price |
|---|---|---|
| Limit BUY | `bar.low <= limit_price` | `limit_price` |
| Limit SELL | `bar.high >= limit_price` | `limit_price` |
| Market BUY | always (against next bar) | `bar.open` |
| Market SELL | always (against next bar) | `bar.open` |

This guarantees no order placed at tick `T` can be informed by data after `T` and still fill within tick `T`'s simulated reality — the fill always occurs on the next bar.

When a fill happens:
- Cash is deducted (BUY) or credited (SELL)
- Position qty is updated
- Order moves from `pending_orders` to `filled_orders`
- All subscribed `fill_callbacks` and `order_update_callbacks` (with status=FILLED) fire

For v1 fills are whole-or-nothing — partial fills are out of scope.

### `backtest/runner.py` — BacktestRunner

Owns the simulated clock and drives the engine through the date range:

```python
class BacktestRunner:
    def __init__(
        self, config: Config, broker: BacktestBroker, clock: SimulatedClock,
        engine: Engine, run_dir: Path,
        start: datetime, end: datetime,
        heartbeat_minutes: int, dream_every_n_days: int,
    ) -> None: ...

    async def run(self) -> dict:
        """Runs the backtest. Returns a manifest dict with summary stats."""
```

Per iteration:
1. If `clock.now() > end`, exit loop
2. If `not is_market_open(clock.now(), config.market_hours, calendar)`, advance clock to the next minute the market is open
3. `broker.process_bar(clock.now())` — matches any pending orders against the latest bar; fires callbacks
4. If the dream cadence is due (last dream was ≥ `dream_every_n_days` simulated days ago), `await engine.run_dream_if_due(now=clock.now())`
5. `await engine.tick(now=clock.now())`
6. `clock.advance(timedelta(minutes=heartbeat_minutes))`

After the loop:
- Run a final consolidation dream regardless of cadence
- Compute final performance summary
- Write `manifest.json` with the run config + headline stats (total P&L, trade count, sharpe-style ratio, etc.)

The runner uses a backtest-specific `DataStore` rooted at the run directory, so all output (trades, equity curve, dreams, learnings, decision logs) is self-contained.

### `backtest/promote.py` — promote-learnings command

```python
async def promote_learnings(run_id: str, live_root: Path = Path(".trading_data")) -> dict:
    """Copies learnings from .trading_data/backtests/<run_id>/learnings/learnings.jsonl
    into live_root/learnings/learnings.jsonl. Appends rather than replacing.
    Tags imported entries with source and confidence. Returns a summary dict."""
```

Each promoted entry gets two extra fields:
- `source: "backtest:<run-id>"` — provenance
- `confidence: "low"` — backtest-derived learnings should be treated more skeptically until validated against real fills

ID collisions: if an imported entry's ID already exists in the live file, the imported entry's ID gets a `_bt_<run-id>` suffix to avoid clobbering. The original ID is preserved in the entry under `original_id`.

The trading agent's prompt includes a sentence: "Entries with `source` starting `backtest:` came from offline simulation. Validate them against real fills before relying heavily on them."

The CLI adds a confirmation prompt before writing:
```
About to import 23 learnings from backtest run 2026-05-04T22-15-00_aapl-spy-jan
into the live system. Continue? [y/N]
```

### `backtest/cli.py` — entry point

```bash
python -m backtest \
  --start 2026-01-01 --end 2026-01-31 \
  --watchlist AAPL,SPY \
  --heartbeat-minutes 5 \
  --dream-every-n-days 7 \
  --starting-cash 100000 \
  --label aapl-spy-jan \
  --bar-interval 1m
```

Reuses the live `config.yaml` for everything not explicitly overridden — safety limits, prompt template, claude timeout, etc. The CLI:

1. Loads `config.yaml`
2. Constructs `HistoricalDataCache`, `SimulatedClock`, `BacktestBroker`
3. Pre-flight: calls `cache.ensure_range(...)` for every symbol in the watchlist over `[start, end]`. Aborts if any range can't be sourced.
4. Constructs an `Engine` instance with the broker's `market_data`, `account`, `orders` (matching the live wiring in `main.py`)
5. Constructs a `BacktestRunner` and calls `runner.run()`
6. Prints the run directory at the end

Promotion command (separate subcommand):

```bash
python -m backtest promote-learnings 2026-05-04T22-15-00_aapl-spy-jan
```

### Production code changes

The harness reuses ~95% of existing code. Required changes to live code:

1. **`main.py`** — extract the `datetime.now().astimezone()` call into a `clock_fn: Callable[[], datetime]` parameter so backtests can substitute the simulated clock. Default value calls `datetime.now().astimezone()` (same behavior as today).
2. **`agent/prompt.py`** — add a sentence to the system prompt about backtest-source learnings being lower-confidence. (One-line addition; harmless when there are no such entries.)
3. **`agent/dream.py`** — when running in backtest mode, skip the "real broker" wording in the dream prompt that doesn't apply. (Optional; backtest still works without this.)

No other production-code changes.

## Initial Conditions

Each backtest starts with a clean account: configurable `--starting-cash` (default $100,000), no open positions, no prior trades, no prior learnings. Backtests are about evaluating strategy from neutral, not picking up where live left off.

If you want to seed a backtest with prior learnings (e.g., to test how a previously-trained agent performs on a new period), copy the learnings file into the run directory before launching. (Out of scope for v1 CLI; manual operation works.)

## Error Handling

| Failure | Handling |
|---|---|
| Missing historical data for requested range | Cache pre-flight before any agent invocation. If moomoo can't supply the range, abort with clear error pointing to the missing window. |
| Agent proposes an option trade | `BacktestOrders.place_order` rejects with `MoomooOrderError("backtest mode: stock-only")`. Agent sees rejection in `recent_proposal_results.json`. System prompt explicitly forbids it. |
| Limit order never fills | Stays pending until cancelled, matching live behavior. End-of-backtest manifest lists never-filled orders. |
| `claude --print` subprocess failure | Engine counts consecutive failures and halts after threshold (existing behavior). Backtest exits with non-zero status. |
| Calendar mismatch (non-trading day) | `BacktestMarketData.get_trading_days` is sourced from the cache (a date is "trading" iff bars exist for it). The runner skips days with no bars automatically. |
| Rate-limit exhaustion during cache fill | Exponential-backoff retries. If exhausted, partial cache is preserved; backtest aborts pointing to the missing range so the user can re-run later when limits reset. |
| Promotion ID collision | Imported entry's ID is suffixed with `_bt_<run-id>`. Original ID preserved as `original_id`. No clobbering. |

## Testing

All tests mock the broker boundary; no live OpenD or claude subprocess calls during tests.

- **`tests/backtest/test_cache.py`** — fetches missing ranges, idempotent re-calls, raises on `load_bars` for missing dates, gap-fill logic
- **`tests/backtest/test_clock.py`** — `now()`, `advance()`, monotonicity
- **`tests/backtest/test_matcher.py`** — limit BUY fills when bar.low ≤ limit, limit SELL fills when bar.high ≥ limit, market orders fill at next bar's open, no fill when bar doesn't cross, cash and positions update correctly
- **`tests/backtest/test_broker.py`** — option proposal rejected; subscription callbacks fire on fills; positions reflect filled orders; balance correctly tracks cash + market value; `get_trading_days` derives from cache
- **`tests/backtest/test_runner.py`** — runner advances clock through trading days, skips weekends/non-trading days, calls `engine.tick`, calls `engine.run_dream_if_due` at configured cadence, writes manifest at end, runs final consolidation dream
- **`tests/backtest/test_promote.py`** — promotion appends entries, tags with `source` and `confidence`, handles ID collisions with `_bt_` suffix and `original_id` preservation, fails clearly if backtest run directory doesn't exist

The agent subprocess is mocked (returns canned `AgentResult`) — the tests verify harness mechanics, not the agent's actual decisions.

## Out of Scope

- Tick-level simulation (no historical tick data from moomoo)
- Options backtesting (no historical chain data)
- Slippage modeling beyond bar-aware fills
- Partial fills
- Multiple-account or portfolio-level backtests
- Scheduled/automatic backtest runs
- Side-by-side strategy comparison (run two backtests, compare manually)
- Replaying live decision logs through the simulator
- Half-day modeling in backtests (treated as full days; minor inaccuracy on ~6 days/year)
