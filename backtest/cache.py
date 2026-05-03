import json
from datetime import date, timedelta
from pathlib import Path

import moomoo as ft
import pandas as pd

from connector.market_data import MarketData


_INTERVAL_TO_KTYPE = {
    "1m": ft.KLType.K_1M,
    "5m": ft.KLType.K_5M,
    "15m": ft.KLType.K_15M,
    "1h": ft.KLType.K_60M,
    "1d": ft.KLType.K_DAY,
}


class HistoricalDataCache:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def ensure_range(
        self, market_data: MarketData, symbol: str, interval: str,
        start: date, end: date,
    ) -> None:
        existing_dates = self._cached_dates(symbol, interval)
        requested_dates = self._all_dates(start, end)
        missing = sorted(requested_dates - existing_dates)
        if not missing:
            return
        ktype = _INTERVAL_TO_KTYPE[interval]
        rows = await market_data.get_price_history(
            symbol, missing[0], missing[-1], ktype,
        )
        self._append_rows(symbol, interval, rows)

    def load_bars(
        self, symbol: str, interval: str, start: date, end: date,
    ) -> pd.DataFrame:
        cache_file = self._cache_path(symbol, interval)
        if not cache_file.exists():
            raise ValueError(f"{symbol} {interval} not in cache")
        rows = [json.loads(line) for line in cache_file.read_text().splitlines() if line.strip()]
        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError(f"{symbol} {interval} not in cache")
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time").reset_index(drop=True)
        mask = (df["time"].dt.date >= start) & (df["time"].dt.date <= end)
        return df.loc[mask].reset_index(drop=True)

    def _cache_path(self, symbol: str, interval: str) -> Path:
        return self._cache_dir / f"{symbol}_{interval}.jsonl"

    def _cached_dates(self, symbol: str, interval: str) -> set[date]:
        cache_file = self._cache_path(symbol, interval)
        if not cache_file.exists():
            return set()
        result: set[date] = set()
        for line in cache_file.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            result.add(date.fromisoformat(str(row["time"])[:10]))
        return result

    @staticmethod
    def _all_dates(start: date, end: date) -> set[date]:
        out = set()
        d = start
        while d <= end:
            out.add(d)
            d = d + timedelta(days=1)
        return out

    def _append_rows(self, symbol: str, interval: str, rows: list[dict]) -> None:
        cache_file = self._cache_path(symbol, interval)
        existing = ""
        if cache_file.exists():
            existing = cache_file.read_text()
        with cache_file.open("w") as f:
            if existing:
                f.write(existing)
                if not existing.endswith("\n"):
                    f.write("\n")
            for row in rows:
                f.write(json.dumps(row, default=str) + "\n")
