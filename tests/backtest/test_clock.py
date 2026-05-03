from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backtest.clock import SimulatedClock


def test_clock_returns_initial_now():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    assert clock.now() == start


def test_clock_advance_moves_now_forward():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == start + timedelta(minutes=5)


def test_clock_advance_is_cumulative():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    clock.advance(timedelta(minutes=5))
    clock.advance(timedelta(minutes=10))
    assert clock.now() == start + timedelta(minutes=15)


def test_clock_set_replaces_current_time():
    start = datetime(2026, 1, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clock = SimulatedClock(start=start)
    new_time = datetime(2026, 2, 1, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    clock.set(new_time)
    assert clock.now() == new_time
