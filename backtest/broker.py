import itertools
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Optional

from connector.exceptions import MoomooMarketDataError, MoomooOrderError
from connector.orders import OrderSpec, OrderStatus

from backtest.cache import HistoricalDataCache
from backtest.clock import SimulatedClock
from backtest.matcher import OrderMatcher, PendingOrder


class BacktestBroker:
    def __init__(
        self, cache: HistoricalDataCache, clock: SimulatedClock,
        watchlist: list[str], interval: str, starting_cash: float,
    ) -> None:
        self._cache = cache
        self._clock = clock
        self._watchlist = watchlist
        self._interval = interval
        self._cash = starting_cash
        self._positions: dict[str, dict] = {}
        self._pending: list[PendingOrder] = []
        self._filled: list[dict] = []
        self._fill_callbacks: list[Callable[[dict], None]] = []
        self._order_update_callbacks: list[Callable[[dict], None]] = []
        self._matcher = OrderMatcher()
        self._id_counter = itertools.count(1)

        self._market_data = _BacktestMarketData(self)
        self._account = _BacktestAccount(self)
        self._orders = _BacktestOrders(self)

    @property
    def market_data(self) -> "_BacktestMarketData": return self._market_data

    @property
    def account(self) -> "_BacktestAccount": return self._account

    @property
    def orders(self) -> "_BacktestOrders": return self._orders

    def process_bar(self, bar_time: datetime) -> None:
        if not self._pending:
            return
        per_symbol_bars = self._latest_bar_for_each_symbol()
        remaining: list[PendingOrder] = []
        for order in self._pending:
            sym_bar = per_symbol_bars.get(order.symbol)
            if sym_bar is None:
                remaining.append(order)
                continue
            fills = self._matcher.process_bar(orders=[order], bar=sym_bar)
            if not fills:
                remaining.append(order)
                continue
            self._apply_fill(order, fills[0])
        self._pending = remaining

    def _latest_bar_for_each_symbol(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        now = self._clock.now()
        # Strip timezone for comparison with naive cache timestamps
        now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
        for sym in self._watchlist:
            try:
                df = self._cache.load_bars(
                    sym, self._interval,
                    now.date() - timedelta(days=1), now.date(),
                )
            except ValueError:
                continue
            if df.empty:
                continue
            df = df[df["time"] <= now_naive]
            if df.empty:
                continue
            row = df.iloc[-1]
            out[sym] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "time": row["time"],
            }
        return out

    def _apply_fill(self, order: PendingOrder, fill: dict) -> None:
        cost = fill["qty"] * fill["price"]
        if order.side == "BUY":
            self._cash -= cost
            pos = self._positions.setdefault(order.symbol, {
                "symbol": order.symbol, "qty": 0, "cost_price": 0.0,
                "current_price": fill["price"], "market_value": 0.0,
                "unrealized_pl": 0.0, "is_option": False,
                "name": order.symbol, "currency": "USD", "side": "LONG",
            })
            old_qty = pos["qty"]
            old_cost = pos["cost_price"]
            new_qty = old_qty + fill["qty"]
            pos["cost_price"] = (
                (old_qty * old_cost + cost) / new_qty if new_qty > 0 else 0.0
            )
            pos["qty"] = new_qty
        else:
            self._cash += cost
            pos = self._positions.get(order.symbol)
            if pos is not None:
                pos["qty"] -= fill["qty"]
                if pos["qty"] <= 0:
                    del self._positions[order.symbol]

        filled_record = {
            "order_id": order.order_id, "symbol": order.symbol,
            "name": order.symbol, "side": order.side,
            "order_type": order.order_type, "price": fill["price"],
            "qty": order.qty, "filled_qty": fill["qty"],
            "avg_fill_price": fill["price"],
            "status": OrderStatus.FILLED, "created_at": fill["filled_at"],
        }
        self._filled.append(filled_record)
        for cb in self._fill_callbacks:
            try:
                cb(fill)
            except Exception:
                pass
        for cb in self._order_update_callbacks:
            try:
                cb({
                    "order_id": order.order_id, "symbol": order.symbol,
                    "side": order.side, "qty": order.qty,
                    "price": fill["price"], "filled_qty": fill["qty"],
                    "order_status": "FILLED_ALL", "updated_at": fill["filled_at"],
                })
            except Exception:
                pass

    def _next_order_id(self) -> str:
        return f"BT-{next(self._id_counter):06d}"


class _BacktestMarketData:
    def __init__(self, broker: BacktestBroker) -> None:
        self._broker = broker

    async def get_quote(self, symbol: str) -> dict:
        bar = self._broker._latest_bar_for_each_symbol().get(symbol)
        if bar is None:
            raise MoomooMarketDataError(f"no bar for {symbol}")
        return {
            "symbol": symbol,
            "last_price": float(bar["close"]),
            "open_price": float(bar["open"]),
            "high_price": float(bar["high"]),
            "low_price": float(bar["low"]),
            "volume": int(bar["volume"]),
            "bid_price": float(bar["close"]) - 0.01,
            "ask_price": float(bar["close"]) + 0.01,
        }

    async def get_price_history(self, symbol, start, end, interval):
        df = self._broker._cache.load_bars(
            symbol, self._broker._interval, start, end,
        )
        return [
            {"time": str(row["time"]), "open": float(row["open"]),
             "close": float(row["close"]), "high": float(row["high"]),
             "low": float(row["low"]), "volume": int(row["volume"]),
             "turnover": float(row.get("turnover", 0.0))}
            for _, row in df.iterrows()
        ]

    async def get_option_chain(self, symbol, expiry):
        raise MoomooMarketDataError("backtest mode: options not supported")

    async def subscribe_quotes(self, symbol, callback) -> None:
        return None

    async def get_trading_days(self, market: str, start, end) -> list[dict]:
        all_dates: set[date] = set()
        for sym in self._broker._watchlist:
            try:
                df = self._broker._cache.load_bars(
                    sym, self._broker._interval, start, end,
                )
            except ValueError:
                continue
            for _, row in df.iterrows():
                t = row["time"]
                d = t.date() if hasattr(t, "date") else date.fromisoformat(str(t)[:10])
                all_dates.add(d)
        return [{"date": d, "type": "WHOLE"} for d in sorted(all_dates)]


class _BacktestAccount:
    def __init__(self, broker: BacktestBroker) -> None:
        self._broker = broker

    async def get_positions(self) -> list[dict]:
        bars = self._broker._latest_bar_for_each_symbol()
        out = []
        for sym, pos in self._broker._positions.items():
            current = float(bars.get(sym, {}).get("close", pos["cost_price"]))
            mv = pos["qty"] * current
            out.append({
                "symbol": sym, "name": sym, "qty": pos["qty"],
                "cost_price": pos["cost_price"], "current_price": current,
                "market_value": mv,
                "unrealized_pl": mv - pos["qty"] * pos["cost_price"],
                "is_option": False, "currency": "USD", "side": "LONG",
            })
        return out

    async def get_balance(self) -> dict:
        positions = await self.get_positions()
        market_value = sum(p["market_value"] for p in positions)
        return {
            "cash": self._broker._cash,
            "buying_power": self._broker._cash,
            "total_assets": self._broker._cash + market_value,
            "market_value": market_value,
            "currency": "USD",
        }

    async def get_account_info(self) -> dict:
        return {
            "account_id": "BACKTEST",
            "currency": "USD",
            "environment": "backtest",
        }


class _BacktestOrders:
    def __init__(self, broker: BacktestBroker) -> None:
        self._broker = broker

    async def place_order(self, spec: OrderSpec) -> str:
        if spec.is_option:
            raise MoomooOrderError("backtest mode: stock-only", error_code=-1)
        order_id = self._broker._next_order_id()
        self._broker._pending.append(PendingOrder(
            order_id=order_id,
            symbol=spec.symbol,
            side=str(spec.side.value).upper(),
            qty=int(spec.qty),
            order_type=str(spec.order_type.value).upper(),
            limit_price=float(spec.price) if spec.order_type.value == "limit" else None,
        ))
        return order_id

    async def cancel_order(self, order_id: str) -> None:
        self._broker._pending = [
            o for o in self._broker._pending if o.order_id != order_id
        ]

    async def modify_order(self, order_id: str, qty: int, price: float) -> None:
        for o in self._broker._pending:
            if o.order_id == order_id:
                o.qty = qty
                o.limit_price = price
                return

    async def get_orders(self, status: OrderStatus) -> list[dict]:
        if status == OrderStatus.FILLED:
            return list(self._broker._filled)
        if status == OrderStatus.PENDING:
            return [
                {"order_id": o.order_id, "symbol": o.symbol, "side": o.side,
                 "qty": o.qty, "filled_qty": 0, "price": o.limit_price or 0.0,
                 "avg_fill_price": 0.0, "status": OrderStatus.PENDING,
                 "name": o.symbol, "order_type": o.order_type,
                 "created_at": str(self._broker._clock.now())}
                for o in self._broker._pending
            ]
        return []

    async def subscribe_fills(self, callback: Callable[[dict], None]) -> None:
        self._broker._fill_callbacks.append(callback)

    async def subscribe_order_updates(self, callback: Callable[[dict], None]) -> None:
        self._broker._order_update_callbacks.append(callback)
