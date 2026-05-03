from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from engine.config import MarketHoursConfig
from engine.market_hours import is_market_open, next_open


@pytest.fixture
def all_days_calendar():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="WHOLE")
    return cal


CONFIG = MarketHoursConfig(open="09:30", close="16:00", early_close="13:00", tz="America/New_York")
NY = ZoneInfo("America/New_York")


def test_is_market_open_during_hours(all_days_calendar):
    now = datetime(2024, 1, 16, 10, 30, tzinfo=NY)  # Tuesday 10:30am ET
    assert is_market_open(now, CONFIG, all_days_calendar) is True


def test_is_market_open_before_open(all_days_calendar):
    now = datetime(2024, 1, 16, 9, 0, tzinfo=NY)  # Tuesday 9:00am ET
    assert is_market_open(now, CONFIG, all_days_calendar) is False


def test_is_market_open_after_close(all_days_calendar):
    now = datetime(2024, 1, 16, 16, 30, tzinfo=NY)  # Tuesday 4:30pm ET
    assert is_market_open(now, CONFIG, all_days_calendar) is False


def test_is_market_open_returns_false_when_calendar_says_non_trading():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=False)
    cal.session_type = MagicMock(return_value=None)
    now = datetime(2024, 1, 13, 10, 30, tzinfo=NY)  # Saturday in this test
    assert is_market_open(now, CONFIG, cal) is False


def test_is_market_open_handles_utc_input(all_days_calendar):
    # 14:30 UTC on Tuesday = 09:30 ET (start of session in standard time)
    now = datetime(2024, 1, 16, 14, 30, tzinfo=ZoneInfo("UTC"))
    assert is_market_open(now, CONFIG, all_days_calendar) is True


def test_next_open_before_today_open(all_days_calendar):
    now = datetime(2024, 1, 16, 7, 0, tzinfo=NY)  # Tuesday early morning
    nxt = next_open(now, CONFIG, all_days_calendar)
    assert nxt.date() == now.date()
    assert nxt.hour == 9 and nxt.minute == 30


def test_next_open_after_today_close(all_days_calendar):
    now = datetime(2024, 1, 16, 17, 0, tzinfo=NY)  # Tuesday after close
    nxt = next_open(now, CONFIG, all_days_calendar)
    assert nxt.date().isoformat() == "2024-01-17"  # Wednesday
    assert nxt.hour == 9 and nxt.minute == 30


def test_next_open_friday_evening_skips_to_monday():
    cal = MagicMock()
    # Returns False for Saturday (2024-01-20) and Sunday (2024-01-21)
    weekend_dates = {date(2024, 1, 20), date(2024, 1, 21)}
    cal.is_trading_day = MagicMock(side_effect=lambda d: d not in weekend_dates)
    now = datetime(2024, 1, 19, 17, 0, tzinfo=NY)  # Friday after close
    nxt = next_open(now, CONFIG, cal)
    assert nxt.date().isoformat() == "2024-01-22"


def test_is_market_open_uses_early_close_on_morning_session():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="MORNING")
    # 14:00 ET on a half day — past early close (13:00) but before regular close (16:00)
    now = datetime(2024, 11, 29, 14, 0, tzinfo=NY)
    assert is_market_open(now, CONFIG, cal) is False


def test_is_market_open_open_before_early_close_on_morning_session():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="MORNING")
    # 12:00 ET on a half day — before early close
    now = datetime(2024, 11, 29, 12, 0, tzinfo=NY)
    assert is_market_open(now, CONFIG, cal) is True


def test_is_market_open_normal_close_on_whole_session():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=True)
    cal.session_type = MagicMock(return_value="WHOLE")
    # 14:00 ET on a normal day — within hours
    now = datetime(2024, 1, 16, 14, 0, tzinfo=NY)
    assert is_market_open(now, CONFIG, cal) is True


def test_next_open_skips_holiday():
    # Calendar says 2024-01-17 (Wednesday) is a non-trading day; 2024-01-18 (Thursday) is a trading day
    cal = MagicMock()
    cal.is_trading_day = MagicMock(side_effect=lambda d: d.isoformat() != "2024-01-17")
    now = datetime(2024, 1, 16, 17, 0, tzinfo=NY)  # Tuesday after close
    nxt = next_open(now, CONFIG, cal)
    assert nxt.date().isoformat() == "2024-01-18"


def test_next_open_raises_when_no_trading_day_within_bound():
    cal = MagicMock()
    cal.is_trading_day = MagicMock(return_value=False)
    now = datetime(2024, 1, 16, 17, 0, tzinfo=NY)
    with pytest.raises(RuntimeError):
        next_open(now, CONFIG, cal)
