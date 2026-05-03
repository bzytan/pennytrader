import os
from pathlib import Path

import pytest
import yaml

from engine.config import Config, MarketHoursConfig, SafetyConfig, load_config


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _valid_config_dict() -> dict:
    return {
        "mode": "paper",
        "heartbeat_interval_seconds": 60,
        "claude_timeout_seconds": 120,
        "market_hours": {"open": "09:30", "close": "16:00", "early_close": "13:00", "tz": "America/New_York"},
        "watchlist": ["AAPL", "SPY"],
        "history": {"interval": "1m", "lookback_hours": 6.5},
        "options": {"nearest_expiries": 2},
        "safety": {
            "max_position_size_pct": 5.0,
            "daily_loss_threshold_pct": 5.0,
            "max_consecutive_agent_failures": 3,
        },
    }


def test_load_config_returns_typed_config(tmp_path):
    path = _write_yaml(tmp_path, _valid_config_dict())
    config = load_config(path)
    assert isinstance(config, Config)
    assert config.mode == "paper"
    assert config.heartbeat_interval_seconds == 60
    assert config.watchlist == ["AAPL", "SPY"]
    assert isinstance(config.market_hours, MarketHoursConfig)
    assert config.market_hours.open == "09:30"
    assert config.market_hours.early_close == "13:00"
    assert isinstance(config.safety, SafetyConfig)
    assert config.safety.max_position_size_pct == 5.0


def test_load_config_paper_mode_does_not_require_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PENNYTRADER_LIVE", raising=False)
    path = _write_yaml(tmp_path, _valid_config_dict())
    config = load_config(path)
    assert config.mode == "paper"


def test_load_config_live_mode_requires_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("PENNYTRADER_LIVE", raising=False)
    data = _valid_config_dict()
    data["mode"] = "live"
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="PENNYTRADER_LIVE"):
        load_config(path)


def test_load_config_live_mode_with_env_var_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("PENNYTRADER_LIVE", "1")
    data = _valid_config_dict()
    data["mode"] = "live"
    path = _write_yaml(tmp_path, data)
    config = load_config(path)
    assert config.mode == "live"


def test_load_config_rejects_unknown_mode(tmp_path):
    data = _valid_config_dict()
    data["mode"] = "demo"
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="mode"):
        load_config(path)
