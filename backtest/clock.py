from datetime import datetime, timedelta


class SimulatedClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set(self, new_time: datetime) -> None:
        self._now = new_time
