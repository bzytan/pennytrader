import json
from datetime import datetime
from typing import Protocol

from agent.dream import DreamRunner
from agent.prompt import PromptBuilder
from agent.runner import AgentResult, AgentRunner
from connector.account import Account
from connector.orders import OrderStatus, Orders
from data.collector import Collector
from data.store import DataStore

from .calendar import TradingCalendar
from .config import Config
from .executor import ProposalExecutor
from .market_hours import is_market_open


class _LogWriter(Protocol):
    def write(self, entry: dict) -> None: ...


class Engine:
    def __init__(
        self,
        config: Config,
        collector: Collector,
        runner: AgentRunner,
        prompt_builder: PromptBuilder,
        account: Account,
        orders: Orders,
        fill_buffer: list[dict],
        order_update_buffer: list[dict],
        executor: ProposalExecutor,
        store: DataStore,
        calendar: TradingCalendar,
        dream_runner: DreamRunner,
        log_writer: _LogWriter,
    ) -> None:
        self._config = config
        self._collector = collector
        self._runner = runner
        self._prompt_builder = prompt_builder
        self._account = account
        self._orders = orders
        self._fill_buffer = fill_buffer
        self._order_update_buffer = order_update_buffer
        self._executor = executor
        self._store = store
        self._calendar = calendar
        self._dream_runner = dream_runner
        self._log_writer = log_writer

        self._baseline_total_assets: float | None = None
        self._consecutive_failures = 0
        self._circuit_breaker_tripped = False
        self._halted = False

    @property
    def circuit_breaker_tripped(self) -> bool:
        return self._circuit_breaker_tripped

    @property
    def halted(self) -> bool:
        return self._halted

    def set_baseline_total_assets(self, value: float) -> None:
        self._baseline_total_assets = value

    async def tick(self, now: datetime) -> None:
        if self._halted:
            return
        if not is_market_open(now, self._config.market_hours, self._calendar):
            return

        recent_fills = list(self._fill_buffer)
        self._fill_buffer.clear()

        recent_order_updates = list(self._order_update_buffer)
        self._order_update_buffer.clear()

        try:
            await self._collector.collect(self._config.watchlist)
        except Exception as exc:
            self._fill_buffer[:0] = recent_fills  # restore fills for next tick
            self._order_update_buffer[:0] = recent_order_updates  # restore updates
            self._log_writer.write({
                "event": "collector_error",
                "time": now.isoformat(),
                "error": repr(exc),
            })
            return

        self._store.atomic_write_text(
            self._store.recent_fills_path(),
            json.dumps(recent_fills, indent=2, default=str),
        )
        self._store.atomic_write_text(
            self._store.recent_order_updates_path(),
            json.dumps(recent_order_updates, indent=2, default=str),
        )

        balance = await self._account.get_balance()
        if self._baseline_total_assets is None:
            self._baseline_total_assets = float(balance["total_assets"])
        daily_pnl = float(balance["total_assets"]) - self._baseline_total_assets

        loss_threshold = (
            self._baseline_total_assets * self._config.safety.daily_loss_threshold_pct / 100.0
        )
        if daily_pnl < -loss_threshold:
            self._fill_buffer[:0] = recent_fills  # preserve unprocessed fills
            self._order_update_buffer[:0] = recent_order_updates
            self._circuit_breaker_tripped = True
            self._log_writer.write({
                "event": "circuit_breaker_tripped",
                "time": now.isoformat(),
                "daily_pnl": daily_pnl,
                "threshold": -loss_threshold,
            })
            return

        # Circuit breaker gates only the agent-and-executor portion
        if self._circuit_breaker_tripped:
            return

        positions = await self._account.get_positions()
        open_orders = await self._orders.get_orders(OrderStatus.PENDING)

        prompt = self._prompt_builder.build(
            now=now,
            balance=balance,
            positions=positions,
            open_orders=open_orders,
            recent_fills=recent_fills,
            recent_order_updates=recent_order_updates,
            daily_pnl=daily_pnl,
        )

        result: AgentResult = await self._runner.run(prompt)

        truncated_stdout = result.stdout if len(result.stdout) <= 4096 else (
            result.stdout[:4096] + f"\n…[truncated, original length {len(result.stdout)}]"
        )
        truncated_stderr = result.stderr if len(result.stderr) <= 4096 else (
            result.stderr[:4096] + f"\n…[truncated, original length {len(result.stderr)}]"
        )

        if result.exit_code != 0 or result.timed_out:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        self._log_writer.write({
            "event": "agent_tick",
            "time": now.isoformat(),
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "timed_out": result.timed_out,
            "stdout": truncated_stdout,
            "stderr": truncated_stderr,
            "daily_pnl": daily_pnl,
            "fills_processed": recent_fills,
            "consecutive_failures": self._consecutive_failures,
        })

        proposal_results = await self._executor.execute(self._store.proposed_trades_path())
        if proposal_results:
            self._store.atomic_write_text(
                self._store.proposal_results_path(),
                json.dumps(proposal_results, indent=2, default=str),
            )
            for r in proposal_results:
                self._log_writer.write({
                    "event": "proposal_executed",
                    "time": now.isoformat(),
                    "result": r,
                })

        if self._consecutive_failures >= self._config.safety.max_consecutive_agent_failures:
            self._halted = True
            self._log_writer.write({
                "event": "halted",
                "time": now.isoformat(),
                "consecutive_failures": self._consecutive_failures,
            })

    async def run_dream_if_due(self, now: datetime) -> None:
        today_str = now.date().isoformat()
        last_path = self._store.last_dream_path()
        if last_path.exists() and last_path.read_text().strip() == today_str:
            return
        try:
            await self._dream_runner.run(now=now)
        except Exception:
            # Dream failures must never halt trading
            pass
