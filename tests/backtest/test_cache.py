import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backtest.cache import HistoricalDataCache


def _market_data_with_history(rows):
    md = MagicMock()
    md.get_price_history = AsyncMock(return_value=rows)
    return md


async def test_ensure_range_fetches_when_cache_empty(tmp_path):
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))
    md.get_price_history.assert_awaited_once()
    cache_file = tmp_path / "AAPL_1m.jsonl"
    assert cache_file.exists()
    line = json.loads(cache_file.read_text().strip())
    assert line["open"] == 100.0


async def test_ensure_range_idempotent_when_already_cached(tmp_path):
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))
    md.get_price_history.reset_mock()
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))
    md.get_price_history.assert_not_awaited()


async def test_ensure_range_fetches_extension(tmp_path):
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 15))

    md.get_price_history = AsyncMock(return_value=[
        {"time": "2026-01-16 09:30:00", "open": 102.0, "close": 103.0,
         "high": 103.5, "low": 101.5, "volume": 1500, "turnover": 154500.0},
    ])
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 16), end=date(2026, 1, 16))

    lines = (tmp_path / "AAPL_1m.jsonl").read_text().splitlines()
    assert len(lines) == 2


async def test_load_bars_returns_dataframe(tmp_path):
    md = _market_data_with_history([
        {"time": "2026-01-15 09:30:00", "open": 100.0, "close": 101.0,
         "high": 101.5, "low": 99.5, "volume": 1000, "turnover": 100500.0},
        {"time": "2026-01-16 09:30:00", "open": 102.0, "close": 103.0,
         "high": 103.5, "low": 101.5, "volume": 1500, "turnover": 154500.0},
    ])
    cache = HistoricalDataCache(cache_dir=tmp_path)
    await cache.ensure_range(market_data=md, symbol="AAPL", interval="1m",
                              start=date(2026, 1, 15), end=date(2026, 1, 16))

    df = cache.load_bars("AAPL", "1m", date(2026, 1, 15), date(2026, 1, 16))
    assert len(df) == 2
    assert df.iloc[0]["open"] == 100.0


def test_load_bars_raises_when_cache_missing(tmp_path):
    cache = HistoricalDataCache(cache_dir=tmp_path)
    with pytest.raises(ValueError, match="not in cache"):
        cache.load_bars("AAPL", "1m", date(2026, 1, 15), date(2026, 1, 15))
