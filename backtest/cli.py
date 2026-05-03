import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent.dream import DreamRunner
from agent.prompt import PromptBuilder
from agent.runner import AgentRunner
from analytics.ledger import Ledger
from analytics.performance import compute_performance
from connector.connection import ConnectionManager, TradingMode
from connector.market_data import MarketData
from data.collector import Collector
from data.store import DataStore
from engine.calendar import TradingCalendar
from engine.config import HistoryConfig, OptionsConfig, load_config
from engine.executor import ProposalExecutor
from engine.loop import Engine
from engine.safe_orders import SafeOrders

from backtest.broker import BacktestBroker
from backtest.cache import HistoricalDataCache
from backtest.clock import SimulatedClock
from backtest.promote import promote_learnings
from backtest.runner import BacktestRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backtest", description="Run pennytrader backtests")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run a backtest")
    run.add_argument("--start", required=True, help="YYYY-MM-DD")
    run.add_argument("--end", required=True, help="YYYY-MM-DD")
    run.add_argument("--watchlist", required=True, help="Comma-separated symbols")
    run.add_argument("--heartbeat-minutes", type=int, default=5)
    run.add_argument("--dream-every-n-days", type=int, default=7)
    run.add_argument("--starting-cash", type=float, default=100000.0)
    run.add_argument("--bar-interval", default="1m")
    run.add_argument("--label", default="run")
    run.add_argument("--config", default="config.yaml")

    promote = sub.add_parser("promote-learnings", help="Promote backtest learnings to live")
    promote.add_argument("run_id")
    promote.add_argument("--live-root", default=".trading_data")
    promote.add_argument("--yes", action="store_true", help="Skip confirmation")

    return parser


async def _run_backtest(args) -> int:
    config = load_config(Path(args.config))
    watchlist = [s.strip() for s in args.watchlist.split(",") if s.strip()]
    # Override config.watchlist so the Engine's collector iterates only the
    # symbols this backtest has cached data for. Without this, the Engine
    # reads watchlist from config.yaml (the live trading list) and fails on
    # any symbol the backtest didn't fetch.
    config.watchlist = watchlist
    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)
    tz = ZoneInfo(config.market_hours.tz)
    open_h, open_m = config.market_hours.open.split(":")
    close_h, close_m = config.market_hours.close.split(":")
    start_dt = datetime.combine(start_d, datetime.min.time(), tzinfo=tz).replace(
        hour=int(open_h), minute=int(open_m),
    )
    end_dt = datetime.combine(end_d, datetime.min.time(), tzinfo=tz).replace(
        hour=int(close_h), minute=int(close_m),
    )

    run_id = f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}_{args.label}"
    live_root = Path(".trading_data")
    run_dir = live_root / "backtests" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_store = DataStore(run_dir)
    run_store.ensure_dirs()

    cache_dir = live_root / "historical_cache"

    print(f"Pre-flight: ensuring cached bars for {watchlist} from {start_d} to {end_d}...")
    cache = HistoricalDataCache(cache_dir=cache_dir)
    mode = TradingMode.PAPER
    async with ConnectionManager(mode=mode) as conn:
        live_md = MarketData(conn)
        for sym in watchlist:
            await cache.ensure_range(
                market_data=live_md, symbol=sym, interval=args.bar_interval,
                start=start_d, end=end_d,
            )

    clock = SimulatedClock(start=start_dt)
    broker = BacktestBroker(
        cache=cache, clock=clock,
        watchlist=watchlist, interval=args.bar_interval,
        starting_cash=args.starting_cash,
    )

    calendar = TradingCalendar(market_data=broker.market_data, market="US")
    await calendar.load(start=start_d, end=end_d)

    history_config = HistoryConfig(interval=args.bar_interval, lookback_hours=6.5)
    options_config = OptionsConfig(nearest_expiries=2)

    def _upcoming_expiries(symbol, n):
        return []

    collector = Collector(
        store=run_store, market_data=broker.market_data, options=broker.market_data,
        account=broker.account, orders=broker.orders,
        history_config=history_config, options_config=options_config,
        upcoming_expiries_provider=_upcoming_expiries,
    )

    fill_buffer: list[dict] = []
    await broker.orders.subscribe_fills(lambda fill: fill_buffer.append(fill))
    order_update_buffer: list[dict] = []
    await broker.orders.subscribe_order_updates(lambda u: order_update_buffer.append(u))

    safe_orders = SafeOrders(
        orders=broker.orders, account=broker.account,
        max_position_size_pct=config.safety.max_position_size_pct,
    )
    executor = ProposalExecutor(safe_orders=safe_orders)
    runner = AgentRunner(timeout_seconds=config.claude_timeout_seconds)
    prompt_builder = PromptBuilder(
        store=run_store, watchlist=watchlist,
        history_interval=args.bar_interval,
        max_position_size_pct=config.safety.max_position_size_pct,
    )

    class _LogWriter:
        """Writes JSONL to disk and prints a human-readable summary to stderr."""
        def __init__(self, store): self._store = store
        def write(self, entry: dict) -> None:
            from datetime import datetime as dt
            path = self._store.decision_log_path(dt.utcnow().date())
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            self._print_summary(entry)

        @staticmethod
        def _print_summary(e: dict) -> None:
            ev = e.get("event", "?")
            t = e.get("time", "")[11:19] if e.get("time") else ""  # HH:MM:SS
            if ev == "agent_tick":
                pnl = e.get("daily_pnl", 0.0)
                dur = e.get("duration_seconds", 0.0)
                exit_code = e.get("exit_code", "?")
                fills = len(e.get("fills_processed", []))
                cf = e.get("consecutive_failures", 0)
                status = "OK" if exit_code == 0 else f"FAIL exit={exit_code}"
                fail_note = f" failures={cf}" if cf else ""
                fill_note = f" fills={fills}" if fills else ""
                print(f"  [{t}] tick {status} ({dur:.1f}s) pnl=${pnl:.2f}{fill_note}{fail_note}",
                      file=sys.stderr, flush=True)
            elif ev == "proposal_executed":
                r = e.get("result", {})
                status = r.get("status", "?")
                if status == "placed":
                    spec = r.get("proposal", {}).get("spec", {})
                    print(f"  [{t}]   → placed {spec.get('side','?')} {spec.get('qty','?')} {spec.get('symbol','?')} @ ${spec.get('price','?')}  id={r.get('order_id','?')}",
                          file=sys.stderr, flush=True)
                elif status == "rejected":
                    print(f"  [{t}]   ✗ rejected: {r.get('error','')[:120]}",
                          file=sys.stderr, flush=True)
                else:
                    print(f"  [{t}]   {status}: {r}", file=sys.stderr, flush=True)
            elif ev == "circuit_breaker_tripped":
                pnl = e.get("daily_pnl", 0.0)
                print(f"  [{t}] !! CIRCUIT BREAKER TRIPPED  daily_pnl=${pnl:.2f}",
                      file=sys.stderr, flush=True)
            elif ev == "halted":
                print(f"  [{t}] !! HALTED  consecutive_failures={e.get('consecutive_failures','?')}",
                      file=sys.stderr, flush=True)
            elif ev == "collector_error":
                print(f"  [{t}] collector_error: {e.get('error','')[:120]}",
                      file=sys.stderr, flush=True)
            elif ev == "dream_completed":
                dur = e.get("duration_seconds", 0.0)
                print(f"  [{t}] dream done ({dur:.1f}s)", file=sys.stderr, flush=True)
            elif ev == "dream_failed":
                phase = e.get("phase", "?")
                print(f"  [{t}] dream FAILED ({phase}): {(e.get('error') or e.get('stderr') or '')[:120]}",
                      file=sys.stderr, flush=True)
            elif ev == "dream_validation_failed":
                print(f"  [{t}] dream rejected (output validation)",
                      file=sys.stderr, flush=True)

    log_writer = _LogWriter(run_store)

    ledger = Ledger(store=run_store)
    dream_runner = DreamRunner(
        ledger=ledger, performance_fn=compute_performance,
        runner=runner, store=run_store, log_writer=log_writer,
        account=broker.account, orders=broker.orders,
    )

    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=broker.account, orders=broker.orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=run_store, calendar=calendar,
        dream_runner=dream_runner, log_writer=log_writer,
    )

    bt_runner = BacktestRunner(
        broker=broker, engine=engine, clock=clock, calendar=calendar,
        market_hours=config.market_hours, run_dir=run_dir,
        start=start_dt, end=end_dt,
        heartbeat_minutes=args.heartbeat_minutes,
        dream_every_n_days=args.dream_every_n_days,
    )

    print(f"Running backtest. Output: {run_dir}", flush=True)
    print(f"  cadence: heartbeat={args.heartbeat_minutes}m, dream every {args.dream_every_n_days} simulated days",
          flush=True)
    print(f"  range: {args.start} → {args.end}, watchlist={watchlist}", flush=True)
    print(f"  log lines below show events as they fire (also captured in {run_dir}/log/)",
          file=sys.stderr, flush=True)

    # Wrap engine.tick and engine.run_dream_if_due to print "starting" notices
    # so silent claude invocations don't look like a hang
    _orig_tick = engine.tick
    _orig_dream = engine.run_dream_if_due
    async def _tick(now):
        print(f"  [{now.strftime('%Y-%m-%d %H:%M')}] tick start...", file=sys.stderr, flush=True)
        return await _orig_tick(now=now)
    async def _dream(now):
        print(f"  [{now.strftime('%Y-%m-%d %H:%M')}] dream start (this can take 30-60s)...",
              file=sys.stderr, flush=True)
        return await _orig_dream(now=now)
    engine.tick = _tick
    engine.run_dream_if_due = _dream

    manifest = await bt_runner.run()
    print(json.dumps(manifest, indent=2))
    print(f"Done. Run directory: {run_dir}")
    return 0


async def _promote(args) -> int:
    if not args.yes:
        ans = input(f"Promote learnings from run {args.run_id} into {args.live_root}? [y/N] ")
        if ans.strip().lower() != "y":
            print("Aborted.")
            return 1
    summary = await promote_learnings(run_id=args.run_id, live_root=Path(args.live_root))
    print(json.dumps(summary, indent=2))
    return 0


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(_run_backtest(args))
    if args.cmd == "promote-learnings":
        return asyncio.run(_promote(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
