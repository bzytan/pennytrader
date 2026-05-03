# Performance Analytics + Self-Learning Design

## Overview

Give the autonomous agent the data and persistent memory it needs to evolve its trading approach over time. Today the agent operates without any memory of its own performance or past lessons — every tick it reasons from scratch. This change adds:

1. A trade ledger (closed trades + equity curve) computed daily from broker data
2. A `performance.json` summary with metrics across multiple time windows
3. Structured persistent learnings the agent reads each trading tick and writes during reflection
4. A daily pre-market "dream" cycle: a separate Claude invocation that reflects on yesterday's data, updates the learnings file, and records its reasoning
5. Dream output validation and provenance so the learning loop is auditable and self-correcting

## Goals

- Surface concrete performance feedback to the agent on every trading tick
- Enable strategy evolution through periodic deliberate reflection (not in-the-moment improvisation)
- Keep the learning loop disciplined: sample-size aware, validated outputs, traceable provenance
- Recompute analytics deterministically from broker truth (no incremental update bugs)

## Non-Goals

- Live intraday metric updates (the agent reads a once-daily snapshot)
- Backtest replay or A/B comparison of strategies (future work)
- Automated strategy selection (the agent is the strategist; this layer just informs it)
- Cross-account or peer-comparative metrics

## Architecture

Two separate flows on the same data substrate:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Pre-market: Dream cycle                       │
│  ┌───────┐    ┌─────────┐    ┌───────────┐    ┌──────────────┐   │
│  │Broker │ →  │ Ledger  │ →  │Performance│ →  │ DreamRunner  │   │
│  │get_   │    │.rebuild │    │.compute   │    │ (claude --   │   │
│  │orders │    │         │    │           │    │  print)      │   │
│  └───────┘    └────┬────┘    └─────┬─────┘    └──────┬───────┘   │
│                    │                │                  │          │
│                    ▼                ▼                  ▼          │
│             ledger/trades.jsonl  performance  learnings/         │
│             ledger/equity_*.jsonl  .json      learnings.jsonl    │
│                                               dreams/YYYY-MM-DD.md│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              Each trading tick: Engine consumes                  │
│                                                                   │
│  PromptBuilder reads performance.json + learnings.jsonl          │
│  → references both in the agent prompt                           │
└─────────────────────────────────────────────────────────────────┘
```

## File Layout

```
.trading_data/
├── ledger/
│   ├── trades.jsonl          # Closed trades, regenerated daily by dream
│   └── equity_curve.jsonl    # Daily total_assets snapshots, appended daily
├── performance.json          # Headline metrics, regenerated daily
├── learnings/
│   └── learnings.jsonl       # Structured persistent observations
├── dreams/
│   └── YYYY-MM-DD.md         # Free-form reflection per dream cycle
└── last_dream.txt            # ISO date of last successful dream
```

## Component Designs

### `analytics/ledger.py` — Ledger

A single class with one public method:

```python
class Ledger:
    def __init__(self, store: DataStore) -> None: ...

    async def rebuild(self, orders: Orders, account: Account) -> None:
        """Fetches the full order history from the broker and recomputes
        the trade ledger and equity curve from scratch."""
```

Internally:

- Fetches all filled orders via `orders.get_orders(OrderStatus.FILLED)`. Note: the moomoo SDK's `order_list_query` returns orders within a recent window (typically last several months by default). The "all_time" metrics in `performance.json` are bounded by what the broker returns — for v1 this is acceptable since the engine itself is new. If a longer historical window is needed later, the ledger can persist its own copy of trades it has seen and merge with broker results.
- Sorts fills by symbol, then by timestamp
- Per-symbol FIFO matching: maintain a queue of open lots from buy fills; sell fills consume oldest lots first; each match emits a closed-trade record:

```json
{
  "symbol": "US.AAPL",
  "side": "long",
  "qty": 10,
  "entry_date": "2026-04-28",
  "entry_price": 150.0,
  "exit_date": "2026-05-02",
  "exit_price": 155.0,
  "pnl": 50.0,
  "holding_period_days": 4,
  "is_option": false
}
```

- Writes the full trade list to `trades.jsonl` (one JSON object per line)
- Appends today's `total_assets` (from `account.get_balance()`) to `equity_curve.jsonl` as `{"date": "YYYY-MM-DD", "total_assets": ..., "cash": ..., "market_value": ...}`. Idempotent — if today's entry already exists, replace it.

Recomputing the trade ledger from scratch each dream cycle keeps the implementation simple and avoids incremental-update bugs. With realistic trade volumes (single-digit to dozens of trades per day), recomputation is cheap.

### `analytics/performance.py` — Performance metrics

A pure function that takes the ledger output and produces `performance.json`:

```python
async def compute_performance(
    store: DataStore, account: Account,
) -> dict:
    """Reads trades.jsonl and equity_curve.jsonl, plus current open positions
    via account.get_positions(), and returns the performance summary dict."""
```

Output shape:

```json
{
  "as_of": "2026-05-04",
  "open_positions_unrealized_pnl": 320.0,
  "today": {"realized_pnl": 0, "trades_closed": 0},
  "last_7_days": {
    "realized_pnl": 1200.0,
    "trades_closed": 18,
    "win_rate": 0.55,
    "avg_winner": 180.0,
    "avg_loser": -90.0,
    "max_drawdown_pct": 2.3
  },
  "last_30_days": { /* same shape */ },
  "all_time": {
    "since": "2026-04-15",
    /* same shape */
  },
  "by_symbol": {
    "AAPL": {"realized_pnl": 850.0, "trades_closed": 8, "win_rate": 0.62, "avg_winner": 200.0, "avg_loser": -100.0},
    "SPY": {"realized_pnl": -120.0, "trades_closed": 5, "win_rate": 0.40, "avg_winner": 80.0, "avg_loser": -110.0}
  }
}
```

`max_drawdown_pct` is computed from the equity curve over the relevant window (peak-to-trough decline). `unrealized_pnl` is sum of `(current_price - cost_basis) * qty` across open positions, derived from current account state.

`compute_performance` writes the result via `DataStore.atomic_write_text` to `performance.json`.

### `analytics/learnings.py` — Learnings store

Structured JSONL — each line is one observation with provenance:

```json
{
  "id": "2026-05-04-001",
  "created_at": "2026-05-04T08:15:00",
  "dream_id": "2026-05-04",
  "category": "timing|sizing|symbol_specific|general",
  "observation": "I lose money when I enter positions in the first 15 minutes of trading.",
  "evidence": "Of 12 trades opened before 09:45 ET in last 30 days, 9 closed at a loss. Average loss $85.",
  "confidence": "medium",
  "supersedes": null,
  "active": true
}
```

A new module `analytics/learnings.py` provides:

```python
class LearningsStore:
    def __init__(self, store: DataStore) -> None: ...

    def read_active(self) -> list[dict]:
        """Returns all entries with active=True, in chronological order."""

    def write(self, entries: list[dict]) -> None:
        """Atomically replaces the file with the given entries. Used by the dream."""
```

The agent (during dream) reads existing entries, decides which to keep, modify, or supersede, and writes back the new full list. Supersession lets the agent retire wrong learnings without losing the audit trail (the original entry stays in the file with `active: false`).

Categories help the agent organize and lets us optionally filter what's surfaced in the trading prompt (e.g., only show top-confidence entries to keep the prompt focused).

### `agent/dream.py` — DreamRunner

```python
class DreamRunner:
    def __init__(
        self, ledger: Ledger, performance_fn, store: DataStore,
        runner: AgentRunner, log_writer,
    ) -> None: ...

    async def run(self, now: datetime) -> bool:
        """Executes one dream cycle. Returns True on success.

        Steps:
        1. Refresh ledger via ledger.rebuild(orders, account)
        2. Call `compute_performance()` to refresh `performance.json`
        3. Build dream prompt
        4. Invoke runner.run(prompt)
        5. Validate outputs (see below)
        6. Update last_dream.txt with today's date
        7. Log dream_completed event
        """
```

**Dream prompt** (separate from the trading prompt):

System instructions:
- Role: reflective analyst, NOT trader; you have read access to all data; you will not place trades
- Goal: identify patterns in the past data and update the learnings file with new observations or refinements
- **Sample size discipline (REQUIRED):** every observation must cite the trade count it's based on; do not propose strategy changes based on fewer than 20 trades unless the pattern is overwhelming (e.g., 5/5)
- Provenance: every entry must include `evidence` (numbers, not vibes); every modification to existing entries must use the supersedes field rather than silent edit
- Output: write a markdown reflection to `dreams/YYYY-MM-DD.md` summarizing what you observed and what you decided to change in learnings; write the updated learnings via `LearningsStore.write()` (or by directly producing the JSONL file at the right path)

Inputs (file paths in the prompt):
- `ledger/trades.jsonl`, `ledger/equity_curve.jsonl`, `performance.json`
- Current `learnings/learnings.jsonl`
- Recent `log/decisions-*.jsonl` files (last 7 days, but the agent can read further back if it wants)

The agent has full Claude Code tool access to read these files, run analysis scripts, etc.

### Output validation

After the dream subprocess returns, before accepting the new `learnings.jsonl`:

1. **File must exist and be parseable JSONL** — if it's missing or malformed, reject and keep the prior version
2. **No more than 50% shrinkage** — if the new file has fewer than half the entries of the prior version, treat as suspicious and keep the prior. (Supersession adds entries, doesn't remove them; large shrinkage suggests the agent overwrote rather than merged.)
3. **Required fields present** on every entry: `id`, `created_at`, `category`, `observation`, `evidence`, `active`

Same validation applies to the dream markdown — if empty or smaller than 200 chars, log a warning but accept (free-form text is harder to validate; the JSONL discipline matters more).

If validation fails, the prior `learnings.jsonl` is preserved, the failure is logged as a `dream_validation_failed` event, and the engine continues normally with stale learnings until the next morning.

### Engine integration

Engine constructor takes a new `dream_runner: DreamRunner` parameter.

A new public method `Engine.run_dream_if_due(now)` checks `last_dream.txt` and triggers a dream if today's date doesn't match. Returns immediately if a dream has already happened today.

Called from main.py's outer loop just before the first trading tick of the day (after the wait-for-market-open sleep, before `engine.tick()`).

### `agent/prompt.py` updates

Add `performance` and `learnings` paths to the data files dict. Add to the system prompt:

```
Past performance and your accumulated learnings are in:
- performance.json — your track record across time windows
- learnings/learnings.jsonl — observations from your previous reflections

Consult both before sizing positions and choosing trades. Active learnings
(active=true) represent your current beliefs about what works and what doesn't.
```

### `main.py` wiring

After `MarketData` and the connector instances are created:

```python
ledger = Ledger(store=store)
dream_runner = DreamRunner(
    ledger=ledger, store=store, runner=runner,
    log_writer=log_writer,
    account=account, orders=orders,
)
```

Pass `dream_runner=dream_runner` to the Engine constructor.

In the outer wait loop, just after waking from after-hours sleep and before calling `engine.tick()`:

```python
await engine.run_dream_if_due(now)
```

## Cold Start

On day 1 (or first run on a new account), the broker has no fill history, so:
- `trades.jsonl` is written as an empty file
- `equity_curve.jsonl` gets one entry (today)
- `performance.json` has zeroed metrics with a `since: today` date
- The first dream runs normally; the agent will produce minimal output (likely a single learning like "no historical data yet — operating on first principles")

This is the desired behavior. No special-case code needed.

## Testing

All tests mock the broker boundary; no live OpenD required.

- **`tests/analytics/test_ledger.py`** (new file):
  - FIFO matching with single buy/sell pair
  - FIFO matching with partial fills (buy 10, sell 4, sell 6)
  - Multiple symbols don't cross
  - Equity curve appends today's snapshot, replaces if same date already present
  - Empty order history → empty trades.jsonl, single equity entry

- **`tests/analytics/test_performance.py`** (new file):
  - Today / 7d / 30d / all_time windows compute correctly
  - Win rate, avg_winner, avg_loser, max_drawdown calculations
  - Per-symbol breakdown
  - Open positions unrealized P&L included
  - Empty ledger → all zeros, sensible defaults

- **`tests/analytics/test_learnings.py`** (new file):
  - `read_active` filters out `active: false` entries
  - `write` is atomic (uses store.atomic_write_text)
  - Empty list write produces an empty file (caller's responsibility to validate)

- **`tests/agent/test_dream.py`** (new file):
  - `DreamRunner.run()` calls ledger rebuild, performance compute, then runner.run with a dream prompt
  - On subprocess success + valid output: updates last_dream.txt, returns True
  - On subprocess failure: returns False, doesn't touch last_dream.txt
  - Output validation: missing learnings.jsonl → rejected, prior preserved
  - Output validation: >50% shrinkage → rejected
  - Output validation: missing required fields → rejected

- **`tests/engine/test_loop.py`** (extend):
  - `run_dream_if_due` triggers when last_dream date != today
  - `run_dream_if_due` skips when last_dream date == today
  - Failure to dream doesn't halt the engine

- **`tests/agent/test_prompt.py`** (extend):
  - Performance and learnings paths included in the prompt
  - System prompt mentions both files

Estimated ~30 new tests on top of the existing 136.

## Error Handling

| Failure | Handling |
|---|---|
| Broker API error during ledger rebuild | Dream fails; logged as `dream_failed`; existing files preserved; trading continues with stale data |
| Subprocess error during dream | Same — logged, rolled back, retry tomorrow |
| Subprocess succeeds but output invalid | Logged as `dream_validation_failed`; prior `learnings.jsonl` preserved; partial files (e.g., dream markdown with no learnings update) discarded |
| `last_dream.txt` missing on first startup | Treated as "no prior dream"; runs immediately |
| Concurrent ticks during a dream | Not possible — the engine's tick loop is sequential and the dream runs between ticks |

## Out of Scope

- Backtesting or what-if analysis
- Cross-day intraday metric snapshots (only EOD)
- Automatic learning expiry (the agent decides what to supersede)
- Multi-strategy comparison (one agent, one strategy stream)
- Decision log compaction or pruning (separate ops concern)
