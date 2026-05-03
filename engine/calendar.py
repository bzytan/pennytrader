from datetime import date
from typing import Literal

from connector.market_data import MarketData


SessionType = Literal["WHOLE", "MORNING", "AFTERNOON"]


class TradingCalendar:
    def __init__(self, market_data: MarketData, market: str = "US") -> None:
        self._market_data = market_data
        self._market = market
        self._cache: dict[date, SessionType] = {}

    async def load(self, start: date, end: date) -> None:
        rows = await self._market_data.get_trading_days(self._market, start, end)
        self._cache = {row["date"]: row["type"] for row in rows}

    def is_trading_day(self, d: date) -> bool:
        return d in self._cache

    def is_half_day(self, d: date) -> bool:
        return self._cache.get(d) in ("MORNING", "AFTERNOON")

    def session_type(self, d: date) -> SessionType | None:
        return self._cache.get(d)
