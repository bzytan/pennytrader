import asyncio
from collections.abc import Callable
from datetime import date

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooMarketDataError


class MarketData:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn
        self._subscription_tasks: list[asyncio.Task] = []

    async def get_quote(self, symbol: str) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_market_snapshot([f"US.{symbol}"]),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        row = data.iloc[0]
        return {
            "symbol": symbol,
            "last_price": float(row["last_price"]),
            "open_price": float(row["open_price"]),
            "high_price": float(row["high_price"]),
            "low_price": float(row["low_price"]),
            "volume": int(row["volume"]),
            "bid_price": float(row["bid_price"]),
            "ask_price": float(row["ask_price"]),
        }

    async def get_price_history(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: ft.KLType,
    ) -> list[dict]:
        loop = asyncio.get_running_loop()
        ret, data, _ = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.request_history_kline(
                f"US.{symbol}",
                start=start.isoformat(),
                end=end.isoformat(),
                ktype=interval,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        return [
            {
                "time": row["time_key"],
                "open": float(row["open"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "volume": int(row["volume"]),
                "turnover": float(row["turnover"]),
            }
            for _, row in data.iterrows()
        ]

    async def get_order_book(self, symbol: str) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_order_book(f"US.{symbol}"),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        return {
            "bids": [
                {"price": float(row["price"]), "volume": int(row["volume"])}
                for _, row in data["Bid"].iterrows()
            ],
            "asks": [
                {"price": float(row["price"]), "volume": int(row["volume"])}
                for _, row in data["Ask"].iterrows()
            ],
        }

    async def subscribe_quotes(self, symbol: str, callback: Callable[[dict], None]) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        class _Handler(ft.StockQuoteHandlerBase):
            def on_recv_rsp(self, rsp_pb) -> tuple:
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code == ft.RET_OK and not content.empty:
                    row = content.iloc[0]
                    loop.call_soon_threadsafe(queue.put_nowait, {
                        "symbol": symbol,
                        "last_price": float(row["last_price"]),
                        "volume": int(row["volume"]),
                    })
                return ret_code, content

        quote_ctx = self._conn.quote_ctx
        quote_ctx.set_handler(_Handler())
        await loop.run_in_executor(
            None,
            lambda: quote_ctx.subscribe([f"US.{symbol}"], [ft.SubType.QUOTE]),
        )
        task = asyncio.create_task(self._dispatch(queue, callback))
        self._subscription_tasks.append(task)

    @staticmethod
    async def _dispatch(queue: asyncio.Queue, callback: Callable[[dict], None]) -> None:
        while True:
            data = await queue.get()
            try:
                callback(data)
            except Exception:
                pass
