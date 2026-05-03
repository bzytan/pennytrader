import os
from datetime import date
from pathlib import Path


class DataStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def ensure_dirs(self) -> None:
        for sub in ("quotes", "history", "options", "account", "log"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def quote_path(self, symbol: str) -> Path:
        return self.root / "quotes" / f"{symbol}.json"

    def history_path(self, symbol: str, interval: str) -> Path:
        return self.root / "history" / f"{symbol}_{interval}.csv"

    def option_chain_path(self, symbol: str, expiry: date) -> Path:
        return self.root / "options" / f"{symbol}_{expiry.isoformat()}.json"

    def positions_path(self) -> Path:
        return self.root / "account" / "positions.json"

    def balance_path(self) -> Path:
        return self.root / "account" / "balance.json"

    def open_orders_path(self) -> Path:
        return self.root / "account" / "orders_open.json"

    def recent_fills_path(self) -> Path:
        return self.root / "account" / "recent_fills.json"

    def proposed_trades_path(self) -> Path:
        return self.root / "account" / "proposed_trades.jsonl"

    def proposal_results_path(self) -> Path:
        return self.root / "account" / "recent_proposal_results.json"

    def decision_log_path(self, day: date) -> Path:
        return self.root / "log" / f"decisions-{day.isoformat()}.jsonl"

    def atomic_write_text(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content)
        os.replace(tmp, target)
