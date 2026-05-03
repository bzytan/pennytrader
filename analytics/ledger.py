import json
import re
from collections import deque
from datetime import date, datetime

from connector.account import Account
from connector.orders import OrderStatus, Orders

from data.store import DataStore


def _is_option_symbol(code: str) -> bool:
    return bool(re.search(r"\d{6}[CP]", code))


def _parse_when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace(" ", "T"))


class Ledger:
    def __init__(self, store: DataStore) -> None:
        self._store = store

    async def rebuild(
        self, orders: Orders, account: Account, today: date,
    ) -> None:
        filled = await orders.get_orders(OrderStatus.FILLED)
        trades = self._compute_trades(filled)
        self._write_trades(trades)
        balance = await account.get_balance()
        self._update_equity_curve(today=today, balance=balance)

    def _compute_trades(self, filled_orders: list[dict]) -> list[dict]:
        fills = sorted(
            filled_orders,
            key=lambda o: _parse_when(str(o["created_at"])),
        )
        open_lots: dict[str, deque] = {}
        trades: list[dict] = []
        for fill in fills:
            symbol = fill["symbol"]
            side = str(fill["side"]).upper()
            qty = int(fill["filled_qty"]) if fill.get("filled_qty") else int(fill["qty"])
            price = float(fill.get("avg_fill_price") or fill["price"])
            when = _parse_when(str(fill["created_at"]))
            lots = open_lots.setdefault(symbol, deque())

            if side == "BUY":
                lots.append({"qty": qty, "price": price, "when": when})
            elif side == "SELL":
                remaining = qty
                while remaining > 0 and lots:
                    lot = lots[0]
                    matched = min(lot["qty"], remaining)
                    pnl = matched * (price - lot["price"])
                    holding = (when.date() - lot["when"].date()).days
                    trades.append({
                        "symbol": symbol,
                        "side": "long",
                        "qty": matched,
                        "entry_date": lot["when"].date().isoformat(),
                        "entry_price": lot["price"],
                        "exit_date": when.date().isoformat(),
                        "exit_price": price,
                        "pnl": pnl,
                        "holding_period_days": holding,
                        "is_option": _is_option_symbol(symbol),
                    })
                    lot["qty"] -= matched
                    remaining -= matched
                    if lot["qty"] == 0:
                        lots.popleft()
        return trades

    def _write_trades(self, trades: list[dict]) -> None:
        body = "\n".join(json.dumps(t, default=str) for t in trades)
        if body:
            body = body + "\n"
        self._store.atomic_write_text(self._store.trades_path(), body)

    def _update_equity_curve(self, today: date, balance: dict) -> None:
        path = self._store.equity_curve_path()
        existing: list[dict] = []
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    existing.append(json.loads(line))
        new_entry = {
            "date": today.isoformat(),
            "total_assets": float(balance["total_assets"]),
            "cash": float(balance["cash"]),
            "market_value": float(balance["market_value"]),
        }
        existing = [e for e in existing if e["date"] != today.isoformat()]
        existing.append(new_entry)
        existing.sort(key=lambda e: e["date"])
        body = "\n".join(json.dumps(e) for e in existing) + "\n"
        self._store.atomic_write_text(path, body)
