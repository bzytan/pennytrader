# Follow-ups

Pending work that has been discussed but not yet completed. New items get added when they come up in conversation; items get removed when completed.

## Designed and planned, not yet built

- **Pre-computed indicators + memory-contract prompt** — spec at `docs/superpowers/specs/2026-05-03-precomputed-indicators-design.md`, plan at `docs/superpowers/plans/2026-05-03-precomputed-indicators.md`. Adds VWAP, SMA(5/20), volume-relative, session high/low, % from open to the per-symbol quote file; appends a memory-contract paragraph to the agent system prompt. Ready to implement.

## Concrete bug fixes

- **First-bar-of-day collector_error edge case.** Every 09:30 ET tick logs `collector_error: MoomooMarketDataError('no bar for <symbol>')` then aborts. Subsequent ticks succeed. Likely an off-by-one in `BacktestBroker._latest_bar_for_each_symbol` — the bar timestamped at exactly the clock's `now()` may be filtered out. Doesn't affect downstream behavior beyond losing the first decision of each day.
- **`config.yaml` is currently tracked in git.** It's user-specific and was committed by mistake during this session. Add to `.gitignore` and `git rm --cached config.yaml` to untrack.
- **Dream cycle reads empty `log/` on first run.** The dream agent reasonably (but wrongly) concluded "decision logs not being written" because the log directory doesn't exist when the dream runs *before* the first tick. Update the dream prompt to clarify that decision logs accumulate during the run and are not expected to exist at the time of the very first dream.
- **Final consolidation dream timed out at 300s.** Surfaced in the rddt-v2 run on 2026-05-03. The end-of-run dream has more data to reflect on than the start-of-run dream. Either bump the timeout for the final dream specifically, or tighten the dream prompt to limit how much the agent ingests.

## Recommended next major work (not yet designed)

- **Live paper-mode shakedown.** Run `python main.py` for several real US trading days during market hours and observe behavior. **This should happen before adding more architectural complexity.** It will surface failure modes that backtests can't (live data feed quirks, OpenD re-login behavior, real-time fill delays, agent reaction to genuinely fresh data). Treat it as the next priority.
- **Risk management layer.** SafeOrders only enforces a per-trade size cap. A real risk system would add: max total exposure per symbol, sector concentration limits, drawdown-aware sizing, position-correlation checks, stop-loss enforcement. Natural next major build after live shakedown.
- **Pre-computed indicators v2.** Larger set (RSI, MACD, ATR, breakout flags, multi-timeframe). Only worth doing if the v1 table-stakes set proves insufficient based on observed agent behavior.

## Operational gaps

- **No systemd / launchd unit for the engine.** Live mode currently assumes manual `python main.py` invocation. For real production, the engine should run as a managed service that auto-restarts on failure.
- **OpenD periodic re-login is unhandled.** Moomoo requires re-authentication every few days. The connector's reconnection logic doesn't address this. A long-running headless deployment will eventually fall over without intervention.
- **No live alert / notification channel.** When the circuit breaker trips or the engine halts, there's no email/SMS/Slack notification. Operator only finds out by checking logs.
- **Backtest dream cadence default may be wasteful.** Default `--dream-every-n-days 7` means weekly dreams. For a 1-week backtest that's just 1 dream. For a 6-month backtest that's ~26 dreams. Worth a sanity check: does weekly cadence still make sense for short backtests?
- **Per-tick `claude --print` latency dominates** wall-clock cost (~90-150s per tick). The precomputed-indicators plan addresses ~30-40s of that. Further options: switch to Haiku model, terser system prompt, batched analysis. Not urgent but a knob to keep in mind.

## Explicitly deferred (decisions documented in CLAUDE.md / specs)

These were considered and consciously chosen NOT to build until live failure modes argue otherwise. Don't reopen casually.

- **Tactical scratch pad memory** between agent ticks — deferred per session discussion. Wait for evidence that conditional plans are getting lost in ways that broker orders can't capture.
- **Multi-broker abstraction** — system is Moomoo-only by design. Adding broker abstraction is a major refactor with no concrete need.
- **Tick-level historical data** — Moomoo doesn't expose it; would require a separate data vendor. Out of scope.
- **Options backtesting** — no historical options chain data from Moomoo. Backtests stay stock-only.
- **Half-day modeling in backtests** — half-days treated as full days; ~6 days/year inaccuracy is acceptable for v1.
- **AFTERMOON-only options sessions** — rare in US markets; treated as WHOLE sessions per spec.
- **Persistent baseline for circuit breaker across restarts** — explicitly deferred in strategy layer spec.
- **Quote subscriptions in live mode** — polling-based collector is sufficient at current heartbeat cadence.
- **Order book in agent context** — discussed, decided low value-to-complexity ratio for current trade sizes.
