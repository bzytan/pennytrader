import asyncio
import re

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooMarketDataError


def _is_option_code(code: str) -> bool:
    return bool(re.search(r'\d{6}[CP]', code))


class Account:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    async def get_positions(self) -> list[dict]:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.position_list_query(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        return [
            {
                "symbol": row["code"],
                "name": row["stock_name"],
                "qty": int(row["qty"]),
                "cost_price": float(row["cost_price"]),
                "market_value": float(row["market_val"]),
                "current_price": float(row["nominal_price"]),
                "unrealized_pl": float(row["pl_val"]),
                "currency": row["currency"],
                "side": row["position_side"],
                "is_option": _is_option_code(row["code"]),
            }
            for _, row in data.iterrows()
        ]

    async def get_balance(self) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.accinfo_query(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        if data.empty:
            raise MoomooMarketDataError("No balance data returned")
        row = data.iloc[0]
        return {
            "cash": float(row["cash"]),
            "buying_power": float(row["power"]),
            "total_assets": float(row["total_assets"]),
            "market_value": float(row["market_val"]),
            "currency": row["currency"],
        }

    async def get_account_info(self) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.get_acc_list(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        if data.empty:
            raise MoomooMarketDataError("No account data returned")
        row = data.iloc[0]
        env = "paper" if self._conn.trd_env == ft.TrdEnv.SIMULATE else "live"
        return {
            "account_id": str(row["acc_id"]),
            "currency": row["currency"],
            "environment": env,
        }
