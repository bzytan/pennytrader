import asyncio
import re
from datetime import date

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooOptionsError


def _parse_expiry_from_contract(contract: str) -> date:
    """Extract expiry from OCC-style contract code e.g. US.AAPL240119C00150000 → 2024-01-19."""
    match = re.search(r'(\d{6})[CP]', contract)
    if not match:
        raise MoomooOptionsError(f"Cannot parse expiry from contract: {contract}")
    raw = match.group(1)
    return date(2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:6]))


def _parse_underlying_from_contract(contract: str) -> str:
    """Extract underlying symbol from contract code e.g. US.AAPL240119C00150000 → AAPL."""
    match = re.search(r'US\.([A-Z]+)\d', contract)
    if not match:
        raise MoomooOptionsError(f"Cannot parse underlying from contract: {contract}")
    return match.group(1)


class Options:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    async def get_option_chain(self, symbol: str, expiry: date) -> list[dict]:
        loop = asyncio.get_running_loop()
        expiry_str = expiry.isoformat()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_option_chain(
                code=f"US.{symbol}",
                start=expiry_str,
                end=expiry_str,
                option_type=ft.OptionType.ALL,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOptionsError(str(data), error_code=ret)
        return [
            {
                "contract": row["code"],
                "option_type": row["option_type"],
                "strike_price": float(row["strike_price"]),
                "expiry": row["strike_time"],
                "lot_size": int(row["lot_size"]),
                "implied_volatility": float(row["implied_volatility"]),
                "delta": float(row["delta"]),
                "gamma": float(row["gamma"]),
                "theta": float(row["theta"]),
                "vega": float(row["vega"]),
            }
            for _, row in data.iterrows()
        ]

    async def get_option_quote(self, contract: str) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_market_snapshot([contract]),
        )
        if ret != ft.RET_OK:
            raise MoomooOptionsError(str(data), error_code=ret)
        row = data.iloc[0]
        return {
            "contract": contract,
            "last_price": float(row["last_price"]),
            "bid_price": float(row["bid_price"]),
            "ask_price": float(row["ask_price"]),
            "volume": int(row["volume"]),
            "open_interest": int(row["open_interest"]),
        }

    async def get_greeks(self, contract: str) -> dict:
        underlying = _parse_underlying_from_contract(contract)
        expiry = _parse_expiry_from_contract(contract)
        chain = await self.get_option_chain(underlying, expiry)
        for entry in chain:
            if entry["contract"] == contract:
                return {
                    "delta": entry["delta"],
                    "gamma": entry["gamma"],
                    "theta": entry["theta"],
                    "vega": entry["vega"],
                    "implied_volatility": entry["implied_volatility"],
                }
        raise MoomooOptionsError(f"Contract not found in chain: {contract}")
