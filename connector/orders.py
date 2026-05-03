import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooOrderError


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


_MOOMOO_STATUS_MAP: dict[str, OrderStatus] = {
    "SUBMITTING": OrderStatus.PENDING,
    "SUBMITTED": OrderStatus.PENDING,
    "FILLED_PART": OrderStatus.PENDING,
    "FILLED_ALL": OrderStatus.FILLED,
    "CANCELLED_PART": OrderStatus.CANCELLED,
    "CANCELLED_ALL": OrderStatus.CANCELLED,
    "FAILED": OrderStatus.FAILED,
    "DISABLED": OrderStatus.FAILED,
    "DELETED": OrderStatus.CANCELLED,
}

_TRADE_SIDE_MAP: dict[TradeSide, ft.TrdSide] = {
    TradeSide.BUY: ft.TrdSide.BUY,
    TradeSide.SELL: ft.TrdSide.SELL,
}

_ORDER_TYPE_MAP: dict[OrderType, ft.OrderType] = {
    OrderType.LIMIT: ft.OrderType.NORMAL,
    OrderType.MARKET: ft.OrderType.MARKET,
}


@dataclass
class OrderSpec:
    symbol: str
    qty: int
    side: TradeSide
    order_type: OrderType
    price: float
    expiry: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[OptionType] = None
    contract_size: Optional[int] = None

    @property
    def is_option(self) -> bool:
        return self.expiry is not None


class Orders:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn
        self._fill_tasks: list[asyncio.Task] = []
        self._order_update_tasks: list[asyncio.Task] = []

    async def place_order(self, spec: OrderSpec) -> str:
        loop = asyncio.get_running_loop()
        code = spec.symbol if spec.is_option else f"US.{spec.symbol}"
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.place_order(
                price=spec.price,
                qty=spec.qty,
                code=code,
                trd_side=_TRADE_SIDE_MAP[spec.side],
                order_type=_ORDER_TYPE_MAP[spec.order_type],
                trd_env=self._conn.trd_env,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)
        if data is None or (hasattr(data, "__len__") and len(data) == 0):
            raise MoomooOrderError("Empty response from place_order", error_code=-1)
        return str(data.iloc[0]["order_id"])

    async def cancel_order(self, order_id: str) -> None:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.modify_order(
                modify_order_op=ft.ModifyOrderOp.CANCEL,
                order_id=order_id,
                qty=0,
                price=0.0,
                trd_env=self._conn.trd_env,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)

    async def modify_order(self, order_id: str, qty: int, price: float) -> None:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.modify_order(
                modify_order_op=ft.ModifyOrderOp.NORMAL,
                order_id=order_id,
                qty=qty,
                price=price,
                trd_env=self._conn.trd_env,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)

    async def get_orders(self, status: OrderStatus) -> list[dict]:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.order_list_query(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)
        results = []
        for _, row in data.iterrows():
            mapped_status = _MOOMOO_STATUS_MAP.get(row["order_status"], OrderStatus.FAILED)
            if mapped_status == status:
                results.append({
                    "order_id": str(row["order_id"]),
                    "symbol": row["code"],
                    "name": row["stock_name"],
                    "side": row["trd_side"],
                    "order_type": row["order_type"],
                    "price": float(row["price"]),
                    "qty": int(row["qty"]),
                    "filled_qty": int(row["dealt_qty"]),
                    "avg_fill_price": float(row["dealt_avg_price"]) if row["dealt_avg_price"] not in (None, "") else 0.0,
                    "status": mapped_status,
                    "created_at": row["create_time"],
                })
        return results

    async def subscribe_fills(self, callback: Callable[[dict], None]) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        class _FillHandler(ft.TradeDealHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code == ft.RET_OK and not content.empty:
                    for _, row in content.iterrows():
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "order_id": str(row["order_id"]),
                            "symbol": row["code"],
                            "side": row["trd_side"],
                            "qty": int(row["qty"]),
                            "price": float(row["price"]),
                            "filled_at": row["create_time"],
                        })
                return ret_code, content

        self._conn.trade_ctx.set_handler(_FillHandler())
        task = asyncio.create_task(self._dispatch_fills(queue, callback))
        self._fill_tasks.append(task)

    @staticmethod
    async def _dispatch_fills(queue: asyncio.Queue, callback: Callable[[dict], None]) -> None:
        while True:
            data = await queue.get()
            try:
                callback(data)
            except Exception:
                pass

    async def subscribe_order_updates(self, callback: Callable[[dict], None]) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        class _OrderUpdateHandler(ft.TradeOrderHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code == ft.RET_OK and not content.empty:
                    for _, row in content.iterrows():
                        updated_at = row.get("updated_time") or row.get("create_time")
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "order_id": str(row["order_id"]),
                            "symbol": row["code"],
                            "side": row["trd_side"],
                            "qty": int(row["qty"]),
                            "price": float(row["price"]),
                            "filled_qty": int(row.get("dealt_qty", 0) or 0),
                            "order_status": row["order_status"],
                            "updated_at": updated_at,
                        })
                return ret_code, content

        self._conn.trade_ctx.set_handler(_OrderUpdateHandler())
        task = asyncio.create_task(self._dispatch_order_updates(queue, callback))
        self._order_update_tasks.append(task)

    @staticmethod
    async def _dispatch_order_updates(queue: asyncio.Queue, callback: Callable[[dict], None]) -> None:
        while True:
            data = await queue.get()
            try:
                callback(data)
            except Exception:
                pass
