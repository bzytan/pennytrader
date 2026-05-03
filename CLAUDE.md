# Project context for Claude Code

This file orients new Claude Code sessions to the pennytrader project.
Read it before making changes.

## What this project is

An autonomous AI trading agent. A long-lived Python process connects to
Moomoo's OpenD broker gateway, observes the market through structured data
files, and uses `claude --print` as its decision layer. A daily "dream"
cycle reviews the agent's recent activity and distills learnings that feed
back into future tick prompts. See `README.md` for the user-facing overview.

The system has both a live engine (`python main.py`) and a backtest harness
(`python -m backtest run ...`) that share the engine, agent, dream, and
analytics code unchanged — only the broker and clock are substituted.

## Where things live

| Path | Purpose |
|---|---|
| `connector/` | Async wrappers over the Moomoo SDK |
| `engine/` | Heartbeat loop, calendar, safety guards |
| `data/` | DataStore (paths + atomic writes), Collector |
| `agent/` | claude --print runner, prompt builder, dream cycle |
| `analytics/` | Trade ledger, performance, learnings store |
| `backtest/` | Backtest broker, clock, matcher, runner, CLI |
| `tests/` | Pytest, mocked at the SDK boundary |
| `docs/superpowers/specs/` | Design specs (`YYYY-MM-DD-<topic>-design.md`) |
| `docs/superpowers/plans/` | Implementation plans matching specs |

## Workflow

We use the superpowers brainstorming → writing-plans → subagent-driven
development workflow for non-trivial changes:

1. `superpowers:brainstorming` — turn idea into a design spec
2. `superpowers:writing-plans` — turn spec into a task-by-task plan
3. `superpowers:subagent-driven-development` — execute via fresh subagent
   per task, with two-stage review

Worktrees go in `.worktrees/<feature-name>/` (gitignored). The
`superpowers:using-git-worktrees` skill creates them.

For tiny mechanical fixes (one-line edits, obvious bug fixes), it is
acceptable to skip the full workflow and commit directly. Use judgment —
when in doubt, brainstorm first.

## Code conventions

- **Python 3.11+**, async throughout
- All synchronous SDK calls wrapped via `asyncio.get_running_loop().run_in_executor`
- Pure functions where reasonable; side effects pushed to module boundaries
- Tests mock at the SDK boundary, never call live OpenD
- Atomic writes (`DataStore.atomic_write_text`) for any file the agent reads
- Match existing module style; don't restructure files outside the task

## Known SDK gotchas

The Moomoo SDK's installed signatures often diverge from documented examples.
Verify against the installed SDK before assuming a method shape:

- **`OpenSecTradeContext` constructor** does NOT take `trd_env` — that's
  passed per-call. Constructor wants `filter_trdmarket=ft.TrdMarket.US`
  and `security_firm=ft.SecurityFirm.FUTUINC`.
- **`get_acc_list()`** takes no arguments. Returns all accounts; filter
  on `trd_env` column client-side to pick paper vs live.
- **`accinfo_query`** defaults to `currency='HKD'`. For US accounts,
  explicitly pass `currency=ft.Currency.USD`.
- **`order_list_query`** returns `dealt_qty` and `dealt_avg_price` columns,
  NOT the documented `filled_qty` / `avg_fill_price`.
- **`get_option_chain`** returns metadata only — NO Greeks, NO pricing.
- **Greeks** come from `get_market_snapshot([contract_code])` under
  `option_*`-prefixed columns: `option_implied_volatility`, `option_delta`,
  `option_gamma`, `option_theta`, `option_vega`, `option_open_interest`.
- **`get_order_book`** requires a prior `subscribe([symbol], [SubType.ORDER_BOOK])`
  call. Not paid — just stateful API. Currently unused by the engine.

When adding a new connector method, **inspect the SDK function signature
first** with `inspect.signature(...)` and call it once against real OpenD
to confirm column names before writing code or tests.

## Other gotchas

- **`claude --print` MUST include `--dangerously-skip-permissions`.**
  Without it, the subprocess hangs silently the first time the agent tries
  to use a tool (Read, Write, Bash) because the permission prompt has no
  visible UI. See `agent/runner.py`.
- **The Collector uses simulated time, not `datetime.now()`.** The Engine
  passes `now=now` to `collector.collect()`. This matters because in
  backtest mode the simulated clock is in the past while wall-clock is
  today — using wall-clock would give the agent empty history files every
  tick.
- **Live and backtest cadences are matched at 5 minutes** by default
  (`heartbeat_interval_seconds: 300`, `--heartbeat-minutes 5`). This is
  intentional — strategy learnings derived from one cadence wouldn't
  transfer cleanly to a 30× different cadence.
- **The agent has no memory between ticks** by design. Persistent intent
  must be encoded as broker orders (stop/limit). The dream cycle is the
  consolidation point. Don't add a tactical scratch pad without strong
  evidence from live failure modes.

## Safety architecture

The agent subprocess has **zero** direct broker access by design. It can
only propose trades by appending JSON lines to `proposed_trades.jsonl`.
The parent process reads, validates via `SafeOrders` (per-trade size cap),
and executes. Three layered guards:

- **SafeOrders** — rejects orders >`safety.max_position_size_pct` of total assets
- **Circuit breaker** — halts agent invocations after `safety.daily_loss_threshold_pct` daily loss
- **Failure halt** — stops engine after `safety.max_consecutive_agent_failures` consecutive subprocess errors

When adding new trade paths, route them through `SafeOrders` — never
expose `connector.orders.Orders` directly to the agent.

## Testing

- Run `pytest tests/ -q` before committing — should report all green
- Mock at the SDK boundary, not at internal interfaces
- Backtest tests use a `BacktestBroker` in place of the connector; never
  touch live OpenD
- Connector tests mock the moomoo SDK return values (DataFrames with the
  correct column names — see SDK gotchas above)

## What NOT to do

- **Don't add features before the live shakedown completes.** Several
  abstractions (scratch pad memory, larger indicator sets, multi-broker
  support) are deliberately deferred until we see real failure modes from
  live paper trading. Premature features solve the wrong problems.
- **Don't bypass the workflow** for non-trivial changes. The
  brainstorm → spec → plan → implement loop catches design issues that
  jumping to code misses.
- **Don't commit `config.yaml`.** It's user-specific. (Note: it is
  currently tracked from a session mistake; if you're cleaning the repo,
  add to `.gitignore` and `git rm --cached`.)
- **Don't introduce dependencies casually.** New deps go through the
  brainstorming step. The current set is minimal: `moomoo-api`, `pyyaml`,
  `pytest`, `pytest-asyncio`.
- **Don't restructure code outside the current task scope.** Improve
  what you touch; leave the rest alone.

## Live mode safety gate

Before running the engine in live mode (real capital):

1. `mode: live` in `config.yaml`
2. `PENNYTRADER_LIVE=1` in the environment

Both required. The engine refuses to start if either is missing. Don't
remove or weaken this gate.
