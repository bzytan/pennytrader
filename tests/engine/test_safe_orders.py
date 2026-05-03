from unittest.mock import AsyncMock, MagicMock

import pytest

from connector.exceptions import MoomooOrderError
from connector.orders import OrderSpec, OrderType, TradeSide
from engine.safe_orders import SafeOrders


def _make_spec(qty=1, price=100.0, symbol="AAPL"):
    return OrderSpec(
        symbol=symbol, qty=qty, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=price,
    )


@pytest.fixture
def orders():
    o = MagicMock()
    o.place_order = AsyncMock(return_value="ORD001")
    o.cancel_order = AsyncMock()
    o.modify_order = AsyncMock()
    o.get_orders = AsyncMock(return_value=[])
    return o


@pytest.fixture
def account():
    a = MagicMock()
    a.get_balance = AsyncMock(return_value={
        "cash": 10000.0, "buying_power": 20000.0,
        "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD",
    })
    return a


async def test_place_order_within_limit_succeeds(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    result = await safe.place_order(_make_spec(qty=10, price=100.0))  # $1,000 vs $100k account
    assert result == "ORD001"
    orders.place_order.assert_awaited_once()


async def test_place_order_exceeding_limit_raises(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    spec = _make_spec(qty=100, price=100.0)  # $10,000 = 10% of $100k, exceeds 5%
    with pytest.raises(MoomooOrderError, match="exceeds max position size"):
        await safe.place_order(spec)
    orders.place_order.assert_not_awaited()


async def test_place_option_order_uses_contract_size(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    from datetime import date
    spec = OrderSpec(
        symbol="US.AAPL240119C00150000", qty=2, side=TradeSide.BUY,
        order_type=OrderType.LIMIT, price=5.50,
        expiry=date(2024, 1, 19), strike=150.0,
        option_type=None, contract_size=100,
    )
    # notional = 2 * 5.50 * 100 = $1,100; 1.1% of $100k → within 5%
    await safe.place_order(spec)
    orders.place_order.assert_awaited_once()


async def test_cancel_order_passes_through(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    await safe.cancel_order("ORD001")
    orders.cancel_order.assert_awaited_once_with("ORD001")


async def test_modify_order_re_checks_size(orders, account):
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    with pytest.raises(MoomooOrderError, match="exceeds max position size"):
        await safe.modify_order("ORD001", qty=100, price=100.0)


async def test_get_orders_passes_through(orders, account):
    from connector.orders import OrderStatus
    safe = SafeOrders(orders=orders, account=account, max_position_size_pct=5.0)
    await safe.get_orders(OrderStatus.PENDING)
    orders.get_orders.assert_awaited_once_with(OrderStatus.PENDING)
