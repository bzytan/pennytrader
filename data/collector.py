import json
from collections.abc import Callable
from datetime import date, datetime, timedelta

import moomoo as ft

from connector.account import Account
from connector.market_data import MarketData
from connector.options import Options
from connector.orders import Orders, OrderStatus
from engine.config import HistoryConfig, OptionsConfig

from .store import DataStore


class Collector:
    def __init__(
        self,
        store: DataStore,
        market_data: MarketData,
        options: Options,
        account: Account,
        orders: Orders,
        history_config: HistoryConfig,
        options_config: OptionsConfig,
        upcoming_expiries_provider: Callable[[str, int], list[date]],
    ) -> None:
        self._store = store
        self._market_data = market_data
        self._options = options
        self._account = account
        self._orders = orders
        self._history_config = history_config
        self._options_config = options_config
        self._upcoming_expiries = upcoming_expiries_provider

    async def collect(self, watchlist: list[str]) -> None:
        for symbol in watchlist:
            await self._write_quote(symbol)
            await self._write_history(symbol)
            await self._write_options(symbol)
        await self._write_account()

    async def _write_quote(self, symbol: str) -> None:
        quote = await self._market_data.get_quote(symbol)
        self._store.atomic_write_text(
            self._store.quote_path(symbol), json.dumps(quote, indent=2)
        )

    async def _write_history(self, symbol: str) -> None:
        end = datetime.now().date()
        start = end - timedelta(days=2)
        ktype = _interval_to_ktype(self._history_config.interval)
        rows = await self._market_data.get_price_history(symbol, start, end, ktype)
        header = "time,open,close,high,low,volume,turnover"
        body = "\n".join(
            f"{r['time']},{r['open']},{r['close']},{r['high']},{r['low']},{r['volume']},{r['turnover']}"
            for r in rows
        )
        self._store.atomic_write_text(
            self._store.history_path(symbol, self._history_config.interval),
            header + "\n" + body + "\n",
        )

    async def _write_options(self, symbol: str) -> None:
        expiries = self._upcoming_expiries(symbol, self._options_config.nearest_expiries)
        for expiry in expiries:
            chain = await self._options.get_option_chain(symbol, expiry)
            self._store.atomic_write_text(
                self._store.option_chain_path(symbol, expiry),
                json.dumps(chain, indent=2),
            )

    async def _write_account(self) -> None:
        positions = await self._account.get_positions()
        balance = await self._account.get_balance()
        open_orders = await self._orders.get_orders(OrderStatus.PENDING)
        self._store.atomic_write_text(
            self._store.positions_path(), json.dumps(positions, indent=2, default=str)
        )
        self._store.atomic_write_text(
            self._store.balance_path(), json.dumps(balance, indent=2, default=str)
        )
        self._store.atomic_write_text(
            self._store.open_orders_path(),
            json.dumps(open_orders, indent=2, default=str),
        )


def _interval_to_ktype(interval: str) -> "ft.KLType":
    mapping = {
        "1m": ft.KLType.K_1M,
        "5m": ft.KLType.K_5M,
        "15m": ft.KLType.K_15M,
        "1h": ft.KLType.K_60M,
        "1d": ft.KLType.K_DAY,
    }
    if interval not in mapping:
        raise ValueError(f"Unsupported history interval: {interval}")
    return mapping[interval]
