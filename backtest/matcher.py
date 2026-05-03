from dataclasses import dataclass
from typing import Optional


@dataclass
class PendingOrder:
    order_id: str
    symbol: str
    side: str          # "BUY" or "SELL"
    qty: int
    order_type: str    # "LIMIT" or "MARKET"
    limit_price: Optional[float]


class OrderMatcher:
    def process_bar(
        self, orders: list[PendingOrder], bar: dict,
    ) -> list[dict]:
        """Returns a list of fill dicts for orders that the bar's range
        crossed. Caller is responsible for removing filled orders from
        their pending list."""
        fills: list[dict] = []
        for order in orders:
            fill = self._try_fill(order, bar)
            if fill is not None:
                fills.append(fill)
        return fills

    def _try_fill(self, order: PendingOrder, bar: dict) -> Optional[dict]:
        if order.order_type == "MARKET":
            price = float(bar["open"])
            return {
                "order_id": order.order_id, "symbol": order.symbol,
                "side": order.side, "qty": order.qty, "price": price,
                "filled_at": str(bar["time"]),
            }
        if order.order_type == "LIMIT":
            limit = float(order.limit_price)
            if order.side == "BUY" and float(bar["low"]) <= limit:
                return {
                    "order_id": order.order_id, "symbol": order.symbol,
                    "side": order.side, "qty": order.qty, "price": limit,
                    "filled_at": str(bar["time"]),
                }
            if order.side == "SELL" and float(bar["high"]) >= limit:
                return {
                    "order_id": order.order_id, "symbol": order.symbol,
                    "side": order.side, "qty": order.qty, "price": limit,
                    "filled_at": str(bar["time"]),
                }
        return None
