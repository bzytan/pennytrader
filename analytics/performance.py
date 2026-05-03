import json
from datetime import date, timedelta
from pathlib import Path

from connector.account import Account

from data.store import DataStore


async def compute_performance(
    store: DataStore, account: Account, today: date,
) -> dict:
    trades = _read_trades(store.trades_path())
    equity = _read_equity_curve(store.equity_curve_path())
    positions = await account.get_positions()
    unrealized = sum(float(p.get("unrealized_pl", 0.0)) for p in positions)

    today_str = today.isoformat()
    one_week = today - timedelta(days=7)
    one_month = today - timedelta(days=30)

    perf = {
        "as_of": today_str,
        "open_positions_unrealized_pnl": unrealized,
        "today": _summarize([t for t in trades if t["exit_date"] == today_str]),
        "last_7_days": _summarize_window(trades, equity, one_week, today),
        "last_30_days": _summarize_window(trades, equity, one_month, today),
        "all_time": _summarize_all_time(trades, equity),
        "by_symbol": _summarize_by_symbol(trades),
    }

    store.atomic_write_text(store.performance_path(), json.dumps(perf, indent=2))
    return perf


def _read_trades(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _read_equity_curve(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _summarize(window_trades: list[dict]) -> dict:
    if not window_trades:
        return {"realized_pnl": 0, "trades_closed": 0, "win_rate": 0,
                "avg_winner": 0, "avg_loser": 0}
    pnls = [float(t["pnl"]) for t in window_trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    return {
        "realized_pnl": sum(pnls),
        "trades_closed": len(window_trades),
        "win_rate": len(winners) / len(window_trades),
        "avg_winner": sum(winners) / len(winners) if winners else 0.0,
        "avg_loser": sum(losers) / len(losers) if losers else 0.0,
    }


def _summarize_window(
    trades: list[dict], equity: list[dict],
    start: date, end: date,
) -> dict:
    start_str = start.isoformat()
    end_str = end.isoformat()
    window_trades = [
        t for t in trades
        if start_str <= t["exit_date"] <= end_str
    ]
    summary = _summarize(window_trades)
    window_equity = [
        e for e in equity
        if start_str <= e["date"] <= end_str
    ]
    summary["max_drawdown_pct"] = _max_drawdown_pct(window_equity)
    return summary


def _summarize_all_time(trades: list[dict], equity: list[dict]) -> dict:
    summary = _summarize(trades)
    summary["max_drawdown_pct"] = _max_drawdown_pct(equity)
    summary["since"] = equity[0]["date"] if equity else None
    return summary


def _max_drawdown_pct(equity: list[dict]) -> float:
    if not equity:
        return 0.0
    peak = float(equity[0]["total_assets"])
    max_dd = 0.0
    for e in equity:
        v = float(e["total_assets"])
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _summarize_by_symbol(trades: list[dict]) -> dict:
    by_sym: dict[str, list[dict]] = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t)
    return {sym: _summarize(ts) for sym, ts in by_sym.items()}
