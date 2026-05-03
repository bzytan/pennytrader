# Strategy Layer Design

## Overview

Build the autonomous trading agent layer for pennytrader. A long-running Python process drives a heartbeat loop that collects market data, hands it to a Claude Code subprocess for reasoning, and lets Claude decide what trades (if any) to place via the existing connector.

The agent is fully autonomous — no human in the loop during operation. It reads market state from files, can write and run Python scripts to analyze the data, and calls connector functions directly to execute trades.

## Goals

- Run as a headless service during US market hours
- Use the local Claude Code CLI (`claude --print`) for AI reasoning, leveraging the user's Claude subscription rather than per-token API billing
- Support multiple symbols on a configurable watchlist with shared buying power
- Provide a structured decision and audit trail for every tick
- Enforce hard safety limits (paper-by-default mode, per-trade size cap, daily loss circuit breaker)
- Be extensible — adding new data sources or trade types should not require restructuring the loop

## Architecture

The system has four layers, each with a single responsibility:

- **Engine** — heartbeat loop, market hours, orchestration, safety checks
- **Data Collector** — fetches market state from the connector and writes structured files
- **Agent** — invokes `claude --print` with a prompt that references data files, captures and logs the result
- **Configuration** — single `config.yaml` controlling all tunable parameters and the watchlist

The agent does not receive raw market data inline. Instead, the prompt contains compact account state plus paths to data files on disk. Claude reads, analyzes, and decides — invoking Python scripts as needed and calling `connector.orders.place_order` directly to execute trades.

## Prerequisite: Fill Subscription on the Connector

The engine relies on real-time order fill notifications so the agent always sees an accurate view of recent fills, regardless of heartbeat interval. The current connector exposes `subscribe_quotes` on `MarketData` but no equivalent for fills.

A small addition to `connector/orders.py` is required before this layer is built:

- `Orders.subscribe_fills(callback)` — registers a fill handler with the trade context, dispatches fill events asynchronously the same way `subscribe_quotes` does

This is a separate spec/plan cycle that lands first.

## Project Structure

```
pennytrader/
├── connector/                 # existing
├── engine/
│   ├── __init__.py
│   ├── loop.py                # heartbeat, orchestration, circuit breaker, tick guard
│   ├── market_hours.py        # US market open/close detection
│   └── safe_orders.py         # size-guarded wrapper around connector.orders.Orders
├── data/
│   ├── __init__.py
│   ├── collector.py           # writes market + account data to files
│   └── store.py               # path conventions, schemas
├── agent/
│   ├── __init__.py
│   ├── runner.py              # subprocess wrapper around `claude --print`
│   └── prompt.py              # builds the prompt (system + state + file paths)
├── tests/
│   ├── engine/
│   ├── data/
│   └── agent/
├── config.yaml                # watchlist + tunable parameters
└── main.py                    # entry point
```

Runtime data lives outside the source tree:

```
.trading_data/
├── quotes/<symbol>.json
├── history/<symbol>_<interval>.csv
├── options/<symbol>_<expiry>.json
├── account/positions.json
├── account/balance.json
├── account/orders_open.json
├── account/recent_fills.json
└── log/decisions-YYYY-MM-DD.jsonl
```

Files are overwritten each tick. Logs rotate daily.

## Configuration

All tunable parameters live in `config.yaml`:

```yaml
mode: paper                      # "paper" | "live"; "live" also requires PENNYTRADER_LIVE=1
heartbeat_interval_seconds: 60   # tick cadence
claude_timeout_seconds: 120      # max wait for agent subprocess

market_hours:
  open: "09:30"
  close: "16:00"
  tz: "America/New_York"

watchlist:
  - AAPL
  - SPY
  - TSLA

history:
  interval: "1m"                 # candle interval for intraday history
  lookback_hours: 6.5

options:
  nearest_expiries: 2            # how many upcoming expiries to fetch chains for

safety:
  max_position_size_pct: 5.0     # single order may not exceed N% of account value
  daily_loss_threshold_pct: 5.0  # halt trading for the day if losses exceed N%
  max_consecutive_agent_failures: 3
```

The engine reads this once at startup. Live mode requires both `mode: live` in config and `PENNYTRADER_LIVE=1` in the environment — this prevents accidentally pointing a paper-tested config at the live broker.

## Module Designs

### `engine/loop.py` — Engine

A single class `Engine` that owns the runtime. Constructed with a config object, a `ConnectionManager`, a `Collector`, and an `AgentRunner`.

**Main loop, on each tick:**

1. If outside market hours, sleep until the next check
2. If circuit breaker tripped today, skip to step 7
3. Run the collector to refresh all data files
4. Drain the fill subscription buffer; append new fills to `recent_fills.json` and the decision log
5. Compute current daily P&L (realized + unrealized); if it exceeds threshold, trip circuit breaker, log, skip to step 7
6. Invoke the agent runner; on completion, append the result to the decision log
7. Sleep until next tick

**Concurrent tick safety:** the loop is strictly sequential — the next tick cannot start until the previous one finishes. If a tick takes longer than `heartbeat_interval_seconds`, the engine logs the overrun and starts the next tick immediately rather than queueing.

**Pre-trade size enforcement:** a thin wrapper module `engine/safe_orders.py` exposes a `SafeOrders` class with the same surface as `connector.orders.Orders`, but `place_order` first checks the order's notional value against `max_position_size_pct` of current account value. If the order is too large, it raises `MoomooOrderError` before the broker call. The agent imports `SafeOrders` (not `Orders`) — this is the only path it has for placing trades.

**Daily P&L baseline:** on engine startup, the engine records the current `total_assets` value as the day's baseline. `daily_pnl = current_total_assets - baseline_total_assets`. If the engine is restarted mid-day, the baseline resets to the value at restart — this is acceptable for v1 since the circuit breaker is a hard floor, not a precise daily accounting tool. Persisting the baseline across restarts is a future improvement.

### `engine/market_hours.py` — MarketHours

Pure function helpers:

- `is_market_open(now: datetime, config: MarketHoursConfig) -> bool`
- `next_open(now: datetime, config: MarketHoursConfig) -> datetime`

US holidays are out of scope for v1 — the engine treats every weekday as a trading day. A future addition can wire in a holiday calendar.

### `data/collector.py` — Collector

A single class with one method:

- `collect(watchlist: list[str]) -> None` — fetches and writes all data files for one tick

The collector pulls from `MarketData`, `Options`, and `Account`. Writes are atomic (write to temp file, rename) so a partial write never leaves the agent reading inconsistent data.

Adding a new data source means adding a new write method here and updating `prompt.py` to reference the new file path. No other modules change.

### `data/store.py` — Store

Constants and helpers for file paths and schemas. The collector and the prompt builder both depend on this so paths stay consistent.

### `agent/runner.py` — AgentRunner

Wraps the subprocess call. Constructed with a config object.

- `run(prompt: str) -> AgentResult` — invokes `claude --print` with the given prompt, captures stdout/stderr, enforces `claude_timeout_seconds`, returns a structured result

`AgentResult` carries: exit code, stdout, stderr, duration, any parsed tool calls. The runner does not interpret trading actions — the agent has already executed them via direct connector calls. The runner only records what the agent did and said.

After `max_consecutive_agent_failures` failed invocations, the engine halts and waits for human intervention.

### `agent/prompt.py` — PromptBuilder

Builds the prompt for each tick. Three parts:

1. **System prompt** (constant): describes the agent's role, available trade types (buy/sell stock, buy call, buy put), how to place trades (`from engine.safe_orders import SafeOrders, OrderSpec, ...`), the safety wrapper behavior, and the principle that taking no action is a valid choice
2. **Current state** (compact, inline): account balance, open positions with cost basis and current P&L, recent fills since last tick, currently open orders, daily P&L so far, time of day
3. **Data file references**: paths and brief schema descriptions for every file in `.trading_data/`

The prompt is rebuilt each tick — there is no conversation history. Each tick is a stateless invocation. State lives in the broker (positions, orders) and the file system (data, logs), not in the agent's context.

## Data Flow

```
                                  ┌──────────────────────┐
                                  │   config.yaml        │
                                  │   watchlist.yaml     │
                                  └──────────┬───────────┘
                                             │
                                             ▼
┌──────────────┐    tick     ┌────────────────────────┐
│  Engine      ├────────────►│  Collector             │
│  loop.py     │             │  data/collector.py     │
└──────┬───────┘             └─────────┬──────────────┘
       │                               │ reads
       │                               ▼
       │                    ┌──────────────────────┐
       │                    │   Connector          │
       │                    │   (existing)         │
       │                    └──────────────────────┘
       │                               │ writes
       │                               ▼
       │                    ┌──────────────────────┐
       │                    │   .trading_data/     │
       │                    └──────────┬───────────┘
       │                               │ paths only
       │                               ▼
       │                    ┌──────────────────────┐
       └───────────────────►│  AgentRunner         │
                            │  agent/runner.py     │
                            └─────────┬────────────┘
                                      │ subprocess
                                      ▼
                            ┌──────────────────────┐
                            │  claude --print      │
                            │  (Claude Code CLI)   │
                            └─────────┬────────────┘
                                      │ direct calls
                                      ▼
                            ┌──────────────────────┐
                            │  engine.safe_orders  │
                            │  (size-guarded)      │
                            └──────────┬───────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │   Connector.Orders   │
                            └──────────────────────┘
```

Quote subscriptions are not used in v1 — the polling-based collector is sufficient given the heartbeat cadence. Fill subscriptions are used because the heartbeat may be longer than the time it takes for an order to fill, and stale fill information would confuse the agent.

## Error Handling

| Failure | Handling |
|---|---|
| OpenD connection drop | Existing `ConnectionManager` reconnects with backoff. Engine logs the gap and continues. |
| Collector failure (SDK error, partial fetch) | Log the error, skip the agent invocation for this tick. Files from the previous tick stay in place; the next tick re-attempts. |
| Claude subprocess timeout / non-zero exit | Log, skip to next tick. After `max_consecutive_agent_failures` consecutive failures, halt. |
| Order rejection (broker error) | The agent sees the `MoomooOrderError` directly and decides whether to retry. The engine does not intervene. |
| Pre-trade size guard rejection | Surface as a `MoomooOrderError` to the agent so it can adjust and retry with a smaller order. |
| Circuit breaker trip | Engine logs, halts new agent invocations until next trading day. Continues collecting data and processing fills so positions remain tracked. |

## Testing

Tests mock the boundary, not the internals.

- **`tests/engine/test_loop.py`** — heartbeat timing, market hours respect, sequential tick guarantee, circuit breaker tripping and reset, halt after consecutive failures
- **`tests/engine/test_market_hours.py`** — open/close detection across edge cases (before open, after close, weekend)
- **`tests/data/test_collector.py`** — file format correctness for each data type, atomic writes, all watchlist symbols covered
- **`tests/data/test_store.py`** — path generation and schema constants
- **`tests/agent/test_runner.py`** — subprocess invocation, timeout handling, output capture, failure counting
- **`tests/agent/test_prompt.py`** — prompt construction with various account states (empty, with positions, with open orders, with recent fills, after circuit breaker trip)

The `claude --print` subprocess is mocked at the boundary. The connector is mocked the same way it was in the connector tests. End-to-end testing happens manually in paper mode before any live deployment.

**Stack:** `pytest` + `pytest-asyncio` (already in pyproject), plus `pyyaml` for config parsing.

## Dependencies

- `pyyaml` — config file parsing
- (Existing) `moomoo-api`, `pytest`, `pytest-asyncio`

The Claude Code CLI must be installed and authenticated on the host running the engine. This is a runtime requirement, not a Python dependency.

## Out of Scope for v1

These are valuable but deliberately deferred:

- **Multi-leg options strategies** (spreads, iron condors) — only single-leg buys for now
- **Selling/writing options** — not in the current trade types
- **Holiday calendar** — every weekday is treated as a trading day
- **Quote subscriptions** — polling is sufficient at current heartbeat cadence
- **Risk management beyond circuit breaker + size cap** — full risk framework is a future layer
- **Agent self-modifying its watchlist** — watchlist is operator-controlled
- **Persistent agent memory across ticks** — each tick is stateless; state is in broker + files
