import asyncio
import contextlib
from enum import Enum

import moomoo as ft

from .exceptions import MoomooConnectionError


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class ConnectionManager:
    def __init__(
        self,
        mode: TradingMode = TradingMode.PAPER,
        host: str = "127.0.0.1",
        port: int = 11111,
    ) -> None:
        self.mode = mode
        self.host = host
        self.port = port
        self._quote_ctx: ft.OpenQuoteContext | None = None
        self._trade_ctx: ft.OpenSecTradeContext | None = None
        self._health_task: asyncio.Task | None = None
        self._connected: bool = False

    @property
    def trd_env(self) -> ft.TrdEnv:
        return ft.TrdEnv.SIMULATE if self.mode == TradingMode.PAPER else ft.TrdEnv.REAL

    @property
    def quote_ctx(self) -> ft.OpenQuoteContext:
        if self._quote_ctx is None:
            raise MoomooConnectionError("Not connected to OpenD")
        return self._quote_ctx

    @property
    def trade_ctx(self) -> ft.OpenSecTradeContext:
        if self._trade_ctx is None:
            raise MoomooConnectionError("Not connected to OpenD")
        return self._trade_ctx

    async def connect(self) -> None:
        await self._connect_contexts()
        self._health_task = asyncio.create_task(self._health_check_loop())

    async def disconnect(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None

        loop = asyncio.get_running_loop()
        if self._quote_ctx:
            await loop.run_in_executor(None, self._quote_ctx.close)
            self._quote_ctx = None
        if self._trade_ctx:
            await loop.run_in_executor(None, self._trade_ctx.close)
            self._trade_ctx = None
        self._connected = False

    async def _connect_contexts(self) -> None:
        loop = asyncio.get_running_loop()

        def _make_contexts() -> tuple[ft.OpenQuoteContext, ft.OpenSecTradeContext]:
            quote_ctx = ft.OpenQuoteContext(host=self.host, port=self.port)
            trade_ctx = ft.OpenSecTradeContext(
                filter_trdmarket=ft.TrdMarket.US,
                host=self.host,
                port=self.port,
                security_firm=ft.SecurityFirm.FUTUINC,
            )
            return quote_ctx, trade_ctx

        try:
            self._quote_ctx, self._trade_ctx = await loop.run_in_executor(None, _make_contexts)
            self._connected = True
        except Exception as e:
            raise MoomooConnectionError(str(e)) from e

    async def _health_check_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                if self._quote_ctx is None:
                    continue
                loop = asyncio.get_running_loop()
                ret, _ = await loop.run_in_executor(None, self._quote_ctx.get_global_state)
                if ret != ft.RET_OK:
                    await self._reconnect()
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._reconnect()

    async def _reconnect(self) -> None:
        self._connected = False
        loop = asyncio.get_running_loop()
        for ctx in (self._quote_ctx, self._trade_ctx):
            if ctx:
                with contextlib.suppress(Exception):
                    await loop.run_in_executor(None, ctx.close)
        self._quote_ctx = None
        self._trade_ctx = None

        backoff = 1
        while not self._connected:
            try:
                await self._connect_contexts()
            except MoomooConnectionError:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 64)

    async def __aenter__(self) -> "ConnectionManager":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()
