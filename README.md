# pennytrader

An autonomous AI trading agent for US stocks and options. The agent runs as a long-lived Python process that connects to Moomoo's OpenD gateway, observes the market through structured data files, and uses the Claude Code CLI (`claude --print`) as its decision layer. Each tick the agent reads market data and account state, optionally proposes trades to a JSON file, and the parent process validates and executes them.

A daily "dream" cycle reviews the agent's recent activity, distills patterns into a structured learnings file, and feeds those learnings back into future tick prompts — so the system gets better over time.

## Architecture

```
            ┌──────────────────┐
            │  Moomoo OpenD    │  (local gateway, ports 11111)
            └─────────┬────────┘
                      │
            ┌─────────▼────────┐
            │  connector/      │  paper/live mode, async wrappers,
            │                  │  fill + order subscriptions
            └─────────┬────────┘
                      │
       ┌──────────────┼───────────────┐
       │              │               │
┌──────▼─────┐  ┌─────▼──────┐  ┌─────▼─────┐
│  data/     │  │  engine/   │  │ analytics/│
│  Collector │  │  Engine    │  │  Ledger,  │
│  + Store   │  │  + Safe    │  │  Perf,    │
│  (files)   │  │  Orders    │  │  Learnings│
└──────┬─────┘  └─────┬──────┘  └─────┬─────┘
       │              │               │
       └──────────────┼───────────────┘
                      │
            ┌─────────▼────────┐
            │  agent/          │  claude --print subprocess
            │  Runner + Prompt │  + daily Dream cycle
            │  + Dream         │
            └──────────────────┘
```

`backtest/` reuses every layer above by substituting a `BacktestBroker` (cached historical bars + simulated state) for the live connector and a `SimulatedClock` for `datetime.now()`.

## Prerequisites

- A funded Moomoo (US) brokerage account with API access enabled
- [Moomoo OpenD](https://www.moomoo.com/us/support/openapi) installed and signed in
- [Claude Code CLI](https://docs.claude.com/claude-code) installed and authenticated
- Python 3.11+

## Setup

```bash
# 1. Clone and install
git clone https://github.com/<you>/pennytrader.git
cd pennytrader
pip install -e ".[dev]"

# 2. Configure
cp config.yaml.example config.yaml
# edit watchlist, safety params, etc. as desired

# 3. Launch OpenD (GUI app), sign in, then click "Unlock Trade"
#    and enter your Moomoo trading password. This is required for any
#    trading API call to work.

# 4. Smoke test the connection
python3 -c "
import asyncio
from connector.connection import ConnectionManager, TradingMode
from connector.account import Account

async def main():
    async with ConnectionManager(mode=TradingMode.PAPER) as conn:
        info = await Account(conn).get_account_info()
        print(info)

asyncio.run(main())
"
# Should print your paper account info with environment='paper'
```

## Running

### Live paper trading

```bash
python3 main.py
```

The engine starts during US market hours (9:30am – 4:00pm ET), runs a startup dream cycle, and then ticks every 5 minutes (default). Outside market hours it sleeps until the next open. Ctrl-C cleanly shuts it down.

Outputs land in `.trading_data/`:

```
.trading_data/
├── quotes/, history/, options/, account/   # current state files
├── ledger/, performance.json               # derived analytics
├── learnings/learnings.jsonl               # dream-distilled wisdom
├── dreams/YYYY-MM-DD.md                    # daily reflections
└── log/decisions-YYYY-MM-DD.jsonl          # per-tick audit log
```

### Backtests

```bash
python3 -m backtest run \
  --start 2026-04-27 --end 2026-05-01 \
  --watchlist RDDT,AAPL \
  --label first-test
```

Each run writes a self-contained directory under `.trading_data/backtests/<run-id>/` with the same shape as live output. Historical bars are cached locally on first fetch.

To copy a backtest's learnings into the live system:

```bash
python3 -m backtest promote-learnings <run-id>
```

Imported entries are tagged with `source: backtest:<run-id>` and `confidence: low` so the live agent treats them with appropriate caution.

## Going live (real money)

The system requires a deliberate double-gate before it will trade real capital:

1. Set `mode: live` in `config.yaml`
2. Export the env var: `PENNYTRADER_LIVE=1`

Both must be present. The engine will refuse to start if you set one but not the other. This prevents accidentally running paper-tested config against the live broker.

```bash
# When you really mean it:
PENNYTRADER_LIVE=1 python3 main.py
```

## Safety model

- **SafeOrders** rejects any single order whose notional exceeds `safety.max_position_size_pct` of total assets (default 5%) before it reaches the broker
- **Circuit breaker** halts new agent invocations for the rest of the day if losses exceed `safety.daily_loss_threshold_pct` (default 5%)
- **Halt-after-failures** stops the engine entirely after `safety.max_consecutive_agent_failures` consecutive Claude subprocess errors (default 5)
- **Capability boundary**: the agent subprocess has zero direct broker access. It can only propose trades by appending to a JSON file; the parent process validates and executes

## Project layout

| Directory | Purpose |
|---|---|
| `connector/` | Async wrappers over the Moomoo SDK |
| `engine/` | Heartbeat loop, market hours/calendar, SafeOrders, ProposalExecutor |
| `data/` | DataStore (paths + atomic writes), Collector (writes per-tick state files) |
| `agent/` | claude --print runner, prompt builder, daily Dream cycle |
| `analytics/` | Trade ledger, performance metrics, structured learnings store |
| `backtest/` | BacktestBroker, SimulatedClock, OrderMatcher, Runner, CLI |
| `docs/superpowers/specs/` | Design specs (one per major feature) |
| `docs/superpowers/plans/` | Implementation plans driving each feature |
| `tests/` | Mocked at the SDK boundary; no live OpenD required |

## Known limitations

- **Options data**: backtests are stock-only — Moomoo doesn't expose historical option chains. Live Greeks may return as 0.0 outside market hours or on lower data tiers.
- **Bar resolution**: 1-minute bars are the floor. No tick-level historical data.
- **One broker**: Moomoo only. No abstraction layer for swapping brokers.
- **Stateless agent ticks**: each tick reads current state; persistent intent must be encoded as broker orders. Long-term memory comes from the dream cycle, not per-tick narrative.
- **Quotas**: Moomoo's free tier limits historical kline fetches (~300/30 days). Backtest cache helps; year-long studies on multiple symbols may exhaust quota.

## License

This is a personal project. Not licensed for external use or redistribution. Trading real capital with this system carries real risk; you alone are responsible for anything it does.
