from datetime import datetime
from zoneinfo import ZoneInfo

from engine.config import MarketHoursConfig
from engine.market_hours import is_market_open, next_open


CONFIG = MarketHoursConfig(open="09:30", close="16:00", tz="America/New_York")
NY = ZoneInfo("America/New_York")


def test_is_market_open_during_hours():
    now = datetime(2024, 1, 16, 10, 30, tzinfo=NY)  # Tuesday 10:30am ET
    assert is_market_open(now, CONFIG) is True


def test_is_market_open_before_open():
    now = datetime(2024, 1, 16, 9, 0, tzinfo=NY)  # Tuesday 9:00am ET
    assert is_market_open(now, CONFIG) is False


def test_is_market_open_after_close():
    now = datetime(2024, 1, 16, 16, 30, tzinfo=NY)  # Tuesday 4:30pm ET
    assert is_market_open(now, CONFIG) is False


def test_is_market_open_on_weekend():
    now = datetime(2024, 1, 13, 10, 30, tzinfo=NY)  # Saturday
    assert is_market_open(now, CONFIG) is False


def test_is_market_open_handles_utc_input():
    # 14:30 UTC on Tuesday = 09:30 ET (start of session in standard time)
    now = datetime(2024, 1, 16, 14, 30, tzinfo=ZoneInfo("UTC"))
    assert is_market_open(now, CONFIG) is True


def test_next_open_before_today_open():
    now = datetime(2024, 1, 16, 7, 0, tzinfo=NY)  # Tuesday early morning
    nxt = next_open(now, CONFIG)
    assert nxt.date() == now.date()
    assert nxt.hour == 9 and nxt.minute == 30


def test_next_open_after_today_close():
    now = datetime(2024, 1, 16, 17, 0, tzinfo=NY)  # Tuesday after close
    nxt = next_open(now, CONFIG)
    assert nxt.date().isoformat() == "2024-01-17"  # Wednesday
    assert nxt.hour == 9 and nxt.minute == 30


def test_next_open_friday_evening_skips_to_monday():
    now = datetime(2024, 1, 19, 17, 0, tzinfo=NY)  # Friday after close
    nxt = next_open(now, CONFIG)
    assert nxt.date().isoformat() == "2024-01-22"  # Monday
