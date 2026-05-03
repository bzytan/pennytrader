from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .calendar import TradingCalendar
from .config import MarketHoursConfig


_MAX_NEXT_OPEN_LOOKAHEAD_DAYS = 14


def _parse_time(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def is_market_open(
    now: datetime, config: MarketHoursConfig, calendar: TradingCalendar,
) -> bool:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    if not calendar.is_trading_day(local.date()):
        return False
    open_t = _parse_time(config.open)
    if calendar.session_type(local.date()) == "MORNING":
        close_t = _parse_time(config.early_close)
    else:
        close_t = _parse_time(config.close)
    return open_t <= local.time() < close_t


def next_open(
    now: datetime, config: MarketHoursConfig, calendar: TradingCalendar,
) -> datetime:
    tz = ZoneInfo(config.tz)
    local = now.astimezone(tz)
    open_t = _parse_time(config.open)

    candidate = local.replace(
        hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0
    )
    if local >= candidate:
        candidate = candidate + timedelta(days=1)
    for _ in range(_MAX_NEXT_OPEN_LOOKAHEAD_DAYS):
        if calendar.is_trading_day(candidate.date()):
            return candidate
        candidate = candidate + timedelta(days=1)
    raise RuntimeError(
        f"No trading day found within {_MAX_NEXT_OPEN_LOOKAHEAD_DAYS} days "
        f"of {now} — calendar may be unloaded or exhausted."
    )
