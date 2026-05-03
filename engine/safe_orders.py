from connector.account import Account
from connector.exceptions import MoomooOrderError
from connector.orders import OrderSpec, Orders, OrderStatus


class SafeOrders:
    def __init__(
        self,
        orders: Orders,
        account: Account,
        max_position_size_pct: float,
    ) -> None:
        self._orders = orders
        self._account = account
        self._max_pct = max_position_size_pct

    async def place_order(self, spec: OrderSpec) -> str:
        await self._enforce_size(spec.qty, spec.price, spec.contract_size, spec.is_option)
        return await self._orders.place_order(spec)

    async def cancel_order(self, order_id: str) -> None:
        await self._orders.cancel_order(order_id)

    async def modify_order(self, order_id: str, qty: int, price: float) -> None:
        await self._enforce_size(qty, price, contract_size=None, is_option=False)
        await self._orders.modify_order(order_id, qty=qty, price=price)

    async def get_orders(self, status: OrderStatus) -> list[dict]:
        return await self._orders.get_orders(status)

    async def _enforce_size(
        self, qty: int, price: float, contract_size: int | None, is_option: bool
    ) -> None:
        balance = await self._account.get_balance()
        total = float(balance["total_assets"])
        multiplier = float(contract_size) if (is_option and contract_size) else 1.0
        notional = qty * price * multiplier
        limit = total * self._max_pct / 100.0
        if notional > limit:
            raise MoomooOrderError(
                f"Order notional ${notional:,.2f} exceeds max position size "
                f"({self._max_pct}% of ${total:,.2f} = ${limit:,.2f})",
                error_code=-1,
            )
