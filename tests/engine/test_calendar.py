from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.calendar import TradingCalendar


@pytest.fixture
def market_data():
    md = MagicMock()
    md.get_trading_days = AsyncMock(return_value=[
        {"date": date(2024, 11, 27), "type": "WHOLE"},
        {"date": date(2024, 11, 29), "type": "MORNING"},
        {"date": date(2024, 12, 2), "type": "WHOLE"},
    ])
    return md


async def test_load_populates_cache(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    market_data.get_trading_days.assert_awaited_once_with(
        "US", date(2024, 11, 27), date(2024, 12, 2)
    )


async def test_is_trading_day_returns_true_for_known_day(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_trading_day(date(2024, 11, 27)) is True
    assert cal.is_trading_day(date(2024, 11, 29)) is True


async def test_is_trading_day_returns_false_for_holiday(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    # 2024-11-28 is Thanksgiving — not in the cache
    assert cal.is_trading_day(date(2024, 11, 28)) is False


async def test_is_trading_day_returns_false_for_date_outside_loaded_range(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_trading_day(date(2025, 1, 1)) is False


async def test_is_half_day_for_morning_session(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_half_day(date(2024, 11, 29)) is True


async def test_is_half_day_for_whole_session(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_half_day(date(2024, 11, 27)) is False


async def test_is_half_day_returns_false_for_non_trading_day(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.is_half_day(date(2024, 11, 28)) is False


async def test_session_type_returns_correct_type(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.session_type(date(2024, 11, 27)) == "WHOLE"
    assert cal.session_type(date(2024, 11, 29)) == "MORNING"


async def test_session_type_returns_none_for_non_trading_day(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))
    assert cal.session_type(date(2024, 11, 28)) is None


async def test_load_replaces_existing_cache(market_data):
    cal = TradingCalendar(market_data=market_data, market="US")
    await cal.load(date(2024, 11, 27), date(2024, 12, 2))

    # Re-load with different data
    market_data.get_trading_days = AsyncMock(return_value=[
        {"date": date(2025, 1, 2), "type": "WHOLE"},
    ])
    await cal.load(date(2025, 1, 1), date(2025, 1, 3))

    # Old entry no longer present
    assert cal.is_trading_day(date(2024, 11, 27)) is False
    # New entry present
    assert cal.is_trading_day(date(2025, 1, 2)) is True
