import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class MarketHoursConfig:
    open: str
    close: str
    early_close: str
    tz: str


@dataclass
class HistoryConfig:
    interval: str
    lookback_hours: float


@dataclass
class OptionsConfig:
    nearest_expiries: int


@dataclass
class SafetyConfig:
    max_position_size_pct: float
    daily_loss_threshold_pct: float
    max_consecutive_agent_failures: int


@dataclass
class Config:
    mode: str
    heartbeat_interval_seconds: int
    claude_timeout_seconds: int
    market_hours: MarketHoursConfig
    watchlist: list[str]
    history: HistoryConfig
    options: OptionsConfig
    safety: SafetyConfig


def load_config(path: Path) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    mode = raw["mode"]
    if mode not in ("paper", "live"):
        raise ValueError(f"Invalid mode: {mode!r}. Must be 'paper' or 'live'.")
    if mode == "live" and os.environ.get("PENNYTRADER_LIVE") != "1":
        raise ValueError(
            "Live mode requires PENNYTRADER_LIVE=1 in the environment as a safety check."
        )

    return Config(
        mode=mode,
        heartbeat_interval_seconds=int(raw["heartbeat_interval_seconds"]),
        claude_timeout_seconds=int(raw["claude_timeout_seconds"]),
        market_hours=MarketHoursConfig(**raw["market_hours"]),
        watchlist=list(raw["watchlist"]),
        history=HistoryConfig(**raw["history"]),
        options=OptionsConfig(**raw["options"]),
        safety=SafetyConfig(**raw["safety"]),
    )
