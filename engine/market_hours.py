from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import MarketHoursConfig


def _parse_time(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def is_market_open(now: datetime, config: MarketHoursConfig) -> bool:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    if local.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_t = _parse_time(config.open)
    close_t = _parse_time(config.close)
    return open_t <= local.time() < close_t


def next_open(now: datetime, config: MarketHoursConfig) -> datetime:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    open_t = _parse_time(config.open)

    candidate = local.replace(
        hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0
    )
    if local >= candidate:
        candidate = candidate + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate = candidate + timedelta(days=1)
    return candidate
