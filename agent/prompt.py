import json
from datetime import datetime
from pathlib import Path

from data.store import DataStore


_SYSTEM_PROMPT = """You are an autonomous trading agent for the pennytrader system.

You manage a real brokerage account. Your goal is to grow capital through informed
decisions about buying/selling stocks and buying single-leg call or put options.

You have full Claude Code tool access: read files, write Python scripts, run them,
and observe results. Market data and account state are written to files before each
of your invocations — read them to understand the current situation.

To execute trades, import and use the size-guarded SafeOrders wrapper:

    from engine.safe_orders import SafeOrders, OrderSpec, OrderStatus, TradeSide, OrderType, OptionType

The wrapper enforces a maximum per-trade size as a percentage of total account value.
Orders that exceed the limit will raise MoomooOrderError — adjust qty and retry if so.

Available trade types:
- Buy or sell stock (OrderSpec with symbol="AAPL", no expiry)
- Buy a call or put option (OrderSpec with symbol set to the contract code, e.g.
  "US.AAPL240119C00150000", and expiry/strike/option_type/contract_size set)

Important:
- Doing nothing is often the right decision. Do not feel obligated to trade.
- Each invocation is stateless — you have no memory of prior ticks. State lives in
  the broker (positions, orders) and the data files.
- Your reasoning and any scripts you run are logged for later review."""


class PromptBuilder:
    def __init__(self, store: DataStore, watchlist: list[str]) -> None:
        self._store = store
        self._watchlist = watchlist

    def build(
        self,
        now: datetime,
        balance: dict,
        positions: list[dict],
        open_orders: list[dict],
        recent_fills: list[dict],
        daily_pnl: float,
    ) -> str:
        state = {
            "time": now.isoformat(),
            "balance": balance,
            "positions": positions,
            "open_orders": open_orders,
            "recent_fills_since_last_tick": recent_fills,
            "daily_pnl": daily_pnl,
        }

        files: dict[str, str] = {
            "positions": str(self._store.positions_path()),
            "balance": str(self._store.balance_path()),
            "open_orders": str(self._store.open_orders_path()),
            "recent_fills": str(self._store.recent_fills_path()),
        }
        for symbol in self._watchlist:
            files[f"quote_{symbol}"] = str(self._store.quote_path(symbol))
            files[f"history_{symbol}"] = str(self._store.history_path(symbol, "1m"))
            files[f"options_dir_{symbol}"] = str(
                self._store.option_chain_path(symbol, _placeholder_date()).parent
            )

        return (
            _SYSTEM_PROMPT
            + "\n\n## Current state\n"
            + json.dumps(state, indent=2, default=str)
            + "\n\n## Data files\n"
            + json.dumps(files, indent=2)
            + "\n\nAssess the situation and decide what to do. Place trades by "
            + "importing SafeOrders and calling place_order, or take no action."
        )


def _placeholder_date():
    from datetime import date
    return date(2000, 1, 1)
