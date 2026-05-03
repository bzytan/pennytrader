import json
from datetime import datetime, timedelta
from pathlib import Path

from engine.config import MarketHoursConfig
from engine.calendar import TradingCalendar
from engine.market_hours import is_market_open

from backtest.clock import SimulatedClock


class BacktestRunner:
    def __init__(
        self, broker, engine, clock: SimulatedClock,
        calendar: TradingCalendar, market_hours: MarketHoursConfig,
        run_dir: Path, start: datetime, end: datetime,
        heartbeat_minutes: int, dream_every_n_days: int,
    ) -> None:
        self._broker = broker
        self._engine = engine
        self._clock = clock
        self._calendar = calendar
        self._market_hours = market_hours
        self._run_dir = Path(run_dir)
        self._start = start
        self._end = end
        self._heartbeat_minutes = heartbeat_minutes
        self._dream_every_n_days = dream_every_n_days

    async def run(self) -> dict:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        last_dream_date = None
        tick_count = 0
        ticks_skipped_closed = 0

        while self._clock.now() <= self._end:
            now = self._clock.now()
            if not is_market_open(now, self._market_hours, self._calendar):
                self._clock.advance(timedelta(minutes=self._heartbeat_minutes))
                ticks_skipped_closed += 1
                continue

            self._broker.process_bar(now)

            if (last_dream_date is None
                    or (now.date() - last_dream_date).days >= self._dream_every_n_days):
                await self._engine.run_dream_if_due(now=now)
                last_dream_date = now.date()

            await self._engine.tick(now=now)
            tick_count += 1

            if getattr(self._engine, "halted", False):
                break

            self._clock.advance(timedelta(minutes=self._heartbeat_minutes))

        # Final consolidation dream
        await self._engine.run_dream_if_due(now=self._clock.now())

        manifest = {
            "start": self._start.isoformat(),
            "end": self._end.isoformat(),
            "heartbeat_minutes": self._heartbeat_minutes,
            "dream_every_n_days": self._dream_every_n_days,
            "tick_count": tick_count,
            "ticks_skipped_market_closed": ticks_skipped_closed,
            "halted": bool(getattr(self._engine, "halted", False)),
        }
        (self._run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest
