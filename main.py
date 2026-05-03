import asyncio
import json
import signal
from datetime import datetime, timedelta
from pathlib import Path

from agent.prompt import PromptBuilder
from agent.runner import AgentRunner
from connector.account import Account
from connector.connection import ConnectionManager, TradingMode
from connector.market_data import MarketData
from connector.options import Options
from connector.orders import Orders
from data.collector import Collector
from data.store import DataStore
from engine.calendar import TradingCalendar
from engine.config import load_config
from engine.executor import ProposalExecutor
from engine.loop import Engine
from engine.market_hours import is_market_open, next_open
from engine.safe_orders import SafeOrders


CONFIG_PATH = Path("config.yaml")
DATA_ROOT = Path(".trading_data")


class JsonlLogWriter:
    def __init__(self, store: DataStore) -> None:
        self._store = store

    def write(self, entry: dict) -> None:
        path = self._store.decision_log_path(datetime.utcnow().date())
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def _upcoming_expiries(symbol: str, n: int):
    # Return the next N Fridays. The agent can refine via scripts later.
    from datetime import date, timedelta
    today = date.today()
    days_to_friday = (4 - today.weekday()) % 7 or 7
    first = today + timedelta(days=days_to_friday)
    return [first + timedelta(days=7 * i) for i in range(n)]


async def main() -> None:
    config = load_config(CONFIG_PATH)
    store = DataStore(DATA_ROOT)
    store.ensure_dirs()

    mode = TradingMode.PAPER if config.mode == "paper" else TradingMode.LIVE
    async with ConnectionManager(mode=mode) as conn:
        market_data = MarketData(conn)
        options = Options(conn)
        account = Account(conn)
        orders = Orders(conn)

        calendar = TradingCalendar(market_data=market_data, market="US")
        today = datetime.now().date()
        await calendar.load(start=today, end=today + timedelta(days=365))

        collector = Collector(
            store=store, market_data=market_data, options=options,
            account=account, orders=orders,
            history_config=config.history, options_config=config.options,
            upcoming_expiries_provider=_upcoming_expiries,
        )

        fill_buffer: list[dict] = []
        await orders.subscribe_fills(lambda fill: fill_buffer.append(fill))

        order_update_buffer: list[dict] = []
        await orders.subscribe_order_updates(lambda update: order_update_buffer.append(update))

        safe_orders = SafeOrders(
            orders=orders, account=account,
            max_position_size_pct=config.safety.max_position_size_pct,
        )
        executor = ProposalExecutor(safe_orders=safe_orders)

        runner = AgentRunner(timeout_seconds=config.claude_timeout_seconds)
        prompt_builder = PromptBuilder(
            store=store, watchlist=config.watchlist,
            history_interval=config.history.interval,
        )
        log_writer = JsonlLogWriter(store)

        engine = Engine(
            config=config, collector=collector, runner=runner,
            prompt_builder=prompt_builder, account=account, orders=orders,
            fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
            log_writer=log_writer, store=store, executor=executor,
            calendar=calendar,
        )

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        while not stop_event.is_set():
            now = datetime.now().astimezone()
            if not is_market_open(now, config.market_hours, calendar):
                wakeup = next_open(now, config.market_hours, calendar)
                wait = max((wakeup - now).total_seconds(), config.heartbeat_interval_seconds)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                continue
            await engine.tick(now=now)
            if engine.halted:
                break
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=config.heartbeat_interval_seconds
                )
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
