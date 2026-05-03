import json
from datetime import datetime
from pathlib import Path

from data.store import DataStore


_SYSTEM_PROMPT = """You are an autonomous trading agent for the pennytrader system.

You manage a real brokerage account. Your goal is to grow capital through informed
decisions about buying/selling stocks and buying single-leg call or put options.

You have full Claude Code tool access: read files, write Python scripts to analyze
the data, and observe results. Market data and account state are written to files
before each of your invocations — read them to understand the current situation.

You DO NOT have direct broker access. To execute a trade, append a JSON line to the
proposed_trades file. The system will read the file after you exit, validate each
proposal against per-trade size limits, and submit approved orders to the broker.
Results from the previous tick (executions, rejections, broker errors) are in the
recent_proposal_results file.
- Broker-side order status changes (rejections, cancellations, partial-fill progress)
  appear in `recent_order_updates_since_last_tick` and the recent_order_updates file
  in real time, as the broker reports them.

Trade proposal schema (one JSON object per line):

  Place a stock order:
    {"action": "place_order", "spec": {"symbol": "AAPL", "qty": 10, "side": "buy",
     "order_type": "limit", "price": 150.0}}

  Place an option order (symbol is the contract code, all option fields required):
    {"action": "place_order", "spec": {"symbol": "US.AAPL240119C00150000", "qty": 1,
     "side": "buy", "order_type": "limit", "price": 5.50, "expiry": "2024-01-19",
     "strike": 150.0, "option_type": "call", "contract_size": 100}}

  Cancel an order:
    {"action": "cancel_order", "order_id": "ORD001"}

  Modify an order:
    {"action": "modify_order", "order_id": "ORD001", "qty": 5, "price": 155.0}

Valid side values: "buy", "sell". Valid order_type values: "limit", "market".
Valid option_type values: "call", "put".

Past performance and your accumulated learnings:
- performance.json — your track record across windows (today, last 7 / 30 days,
  all-time, per-symbol breakdown), plus open-position unrealized P&L.
- learnings/learnings.jsonl — observations from your prior reflections. Active
  entries (active=true) represent your current beliefs about what works and
  what doesn't. Consult both before sizing positions and choosing trades.

Important:
- Doing nothing is often the right decision. Do not feel obligated to trade.
- Each invocation is stateless — you have no memory of prior ticks. State lives in
  the broker (positions, orders, fills) and the data files.
- Per-trade size cap is enforced by the system; oversized proposals will be rejected.
- Your reasoning, scripts you run, and proposals are all logged for later review."""


class PromptBuilder:
    def __init__(self, store: DataStore, watchlist: list[str], history_interval: str) -> None:
        self._store = store
        self._watchlist = watchlist
        self._history_interval = history_interval

    def build(
        self,
        now: datetime,
        balance: dict,
        positions: list[dict],
        open_orders: list[dict],
        recent_fills: list[dict],
        recent_order_updates: list[dict],
        daily_pnl: float,
    ) -> str:
        state = {
            "time": now.isoformat(),
            "balance": balance,
            "positions": positions,
            "open_orders": open_orders,
            "recent_fills_since_last_tick": recent_fills,
            "recent_order_updates_since_last_tick": recent_order_updates,
            "daily_pnl": daily_pnl,
        }

        files: dict[str, str] = {
            "positions": str(self._store.positions_path()),
            "balance": str(self._store.balance_path()),
            "open_orders": str(self._store.open_orders_path()),
            "recent_fills": str(self._store.recent_fills_path()),
            "recent_order_updates": str(self._store.recent_order_updates_path()),
            "proposed_trades": str(self._store.proposed_trades_path()),
            "recent_proposal_results": str(self._store.proposal_results_path()),
            "performance": str(self._store.performance_path()),
            "learnings": str(self._store.learnings_path()),
        }
        for symbol in self._watchlist:
            files[f"quote_{symbol}"] = str(self._store.quote_path(symbol))
            files[f"history_{symbol}"] = str(self._store.history_path(symbol, self._history_interval))
            files[f"options_dir_{symbol}"] = str(
                self._store.option_chain_path(symbol, _placeholder_date()).parent
            )

        return (
            _SYSTEM_PROMPT
            + "\n\n## Current state\n"
            + json.dumps(state, indent=2, default=str)
            + "\n\n## Data files\n"
            + json.dumps(files, indent=2)
            + "\n\nAssess the situation and decide what to do. To trade, append JSON "
            + "proposals to the proposed_trades file, or take no action."
        )


def _placeholder_date():
    from datetime import date
    return date(2000, 1, 1)
