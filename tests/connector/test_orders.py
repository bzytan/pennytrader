import pandas as pd
import pytest
import moomoo as ft
from datetime import date
from unittest.mock import MagicMock
from connector.connection import ConnectionManager
from connector.orders import Orders, OrderSpec, OrderStatus, TradeSide, OrderType, OptionType
from connector.exceptions import MoomooOrderError


@pytest.fixture
def mock_conn():
    conn = MagicMock(spec=ConnectionManager)
    conn.trade_ctx = MagicMock()
    conn.trd_env = ft.TrdEnv.SIMULATE
    return conn


async def test_place_stock_order_returns_order_id(mock_conn):
    df = pd.DataFrame([{"order_id": "ORD001"}])
    mock_conn.trade_ctx.place_order.return_value = (ft.RET_OK, df)

    orders = Orders(mock_conn)
    spec = OrderSpec(
        symbol="AAPL",
        qty=10,
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        price=150.0,
    )
    result = await orders.place_order(spec)

    assert result == "ORD001"
    mock_conn.trade_ctx.place_order.assert_called_once()


async def test_place_option_order_returns_order_id(mock_conn):
    df = pd.DataFrame([{"order_id": "ORD002"}])
    mock_conn.trade_ctx.place_order.return_value = (ft.RET_OK, df)

    orders = Orders(mock_conn)
    spec = OrderSpec(
        symbol="US.AAPL240119C00150000",
        qty=2,
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        price=5.50,
        expiry=date(2024, 1, 19),
        strike=150.0,
        option_type=OptionType.CALL,
        contract_size=100,
    )
    result = await orders.place_order(spec)

    assert result == "ORD002"


async def test_place_order_raises_on_sdk_error(mock_conn):
    mock_conn.trade_ctx.place_order.return_value = (ft.RET_ERROR, "Order rejected")

    orders = Orders(mock_conn)
    spec = OrderSpec(
        symbol="AAPL",
        qty=10,
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        price=150.0,
    )
    with pytest.raises(MoomooOrderError):
        await orders.place_order(spec)


async def test_cancel_order_succeeds(mock_conn):
    df = pd.DataFrame([{"order_id": "ORD001"}])
    mock_conn.trade_ctx.modify_order.return_value = (ft.RET_OK, df)

    orders = Orders(mock_conn)
    await orders.cancel_order("ORD001")

    mock_conn.trade_ctx.modify_order.assert_called_once()


async def test_cancel_order_raises_on_sdk_error(mock_conn):
    mock_conn.trade_ctx.modify_order.return_value = (ft.RET_ERROR, "Cancel failed")

    orders = Orders(mock_conn)
    with pytest.raises(MoomooOrderError):
        await orders.cancel_order("ORD001")


async def test_modify_order_succeeds(mock_conn):
    df = pd.DataFrame([{"order_id": "ORD001"}])
    mock_conn.trade_ctx.modify_order.return_value = (ft.RET_OK, df)

    orders = Orders(mock_conn)
    await orders.modify_order("ORD001", qty=5, price=155.0)

    mock_conn.trade_ctx.modify_order.assert_called_once()


async def test_get_orders_filters_by_status(mock_conn):
    df = pd.DataFrame([{
        "order_id": "ORD001",
        "code": "US.AAPL",
        "stock_name": "Apple Inc.",
        "trd_side": "BUY",
        "order_type": "NORMAL",
        "price": 150.0,
        "qty": 10,
        "filled_qty": 0,
        "avg_fill_price": 0.0,
        "order_status": "SUBMITTED",
        "create_time": "2024-01-15 10:00:00",
    }])
    mock_conn.trade_ctx.order_list_query.return_value = (ft.RET_OK, df)

    orders = Orders(mock_conn)
    result = await orders.get_orders(OrderStatus.PENDING)

    assert len(result) == 1
    assert result[0]["order_id"] == "ORD001"
    assert result[0]["symbol"] == "US.AAPL"
    assert result[0]["price"] == 150.0
    assert result[0]["status"] == OrderStatus.PENDING


async def test_get_orders_excludes_non_matching_status(mock_conn):
    df = pd.DataFrame([{
        "order_id": "ORD001",
        "code": "US.AAPL",
        "stock_name": "Apple Inc.",
        "trd_side": "BUY",
        "order_type": "NORMAL",
        "price": 150.0,
        "qty": 10,
        "filled_qty": 0,
        "avg_fill_price": 0.0,
        "order_status": "SUBMITTED",
        "create_time": "2024-01-15 10:00:00",
    }])
    mock_conn.trade_ctx.order_list_query.return_value = (ft.RET_OK, df)

    orders = Orders(mock_conn)
    result = await orders.get_orders(OrderStatus.FILLED)

    assert len(result) == 0


async def test_get_orders_raises_on_sdk_error(mock_conn):
    mock_conn.trade_ctx.order_list_query.return_value = (ft.RET_ERROR, "Error")

    orders = Orders(mock_conn)
    with pytest.raises(MoomooOrderError):
        await orders.get_orders(OrderStatus.PENDING)


async def test_order_spec_is_option_property():
    spec = OrderSpec(
        symbol="US.AAPL240119C00150000",
        qty=1,
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        price=5.0,
        expiry=date(2024, 1, 19),
        strike=150.0,
        option_type=OptionType.CALL,
        contract_size=100,
    )
    assert spec.is_option is True

    stock_spec = OrderSpec(
        symbol="AAPL",
        qty=1,
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        price=150.0,
    )
    assert stock_spec.is_option is False
