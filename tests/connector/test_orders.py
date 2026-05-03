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
    call_kwargs = mock_conn.trade_ctx.place_order.call_args.kwargs
    assert call_kwargs["code"] == "US.AAPL240119C00150000"


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
    call_kwargs = mock_conn.trade_ctx.modify_order.call_args.kwargs
    assert call_kwargs["modify_order_op"] == ft.ModifyOrderOp.CANCEL


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
    call_kwargs = mock_conn.trade_ctx.modify_order.call_args.kwargs
    assert call_kwargs["modify_order_op"] == ft.ModifyOrderOp.NORMAL


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


async def test_subscribe_fills_registers_handler(mock_conn):
    orders = Orders(mock_conn)
    received = []
    await orders.subscribe_fills(lambda fill: received.append(fill))

    mock_conn.trade_ctx.set_handler.assert_called_once()


async def test_subscribe_fills_dispatches_fill_to_callback(mock_conn):
    import asyncio
    import moomoo as ft
    from unittest.mock import patch

    orders = Orders(mock_conn)
    received: list[dict] = []
    done = asyncio.Event()

    def callback(fill):
        received.append(fill)
        done.set()

    await orders.subscribe_fills(callback)

    handler = mock_conn.trade_ctx.set_handler.call_args.args[0]
    fill_df = pd.DataFrame([{
        "order_id": "ORD001",
        "code": "US.AAPL",
        "trd_side": "BUY",
        "qty": 10,
        "price": 150.0,
        "create_time": "2024-01-15 10:00:00",
    }])

    with patch.object(ft.TradeDealHandlerBase, "on_recv_rsp", return_value=(ft.RET_OK, fill_df)):
        handler.on_recv_rsp(object())  # rsp_pb sentinel — super() is mocked

    await asyncio.wait_for(done.wait(), timeout=1.0)
    assert received[0]["order_id"] == "ORD001"
    assert received[0]["symbol"] == "US.AAPL"
    assert received[0]["qty"] == 10
    assert received[0]["price"] == 150.0


async def test_subscribe_order_updates_registers_handler(mock_conn):
    orders = Orders(mock_conn)
    received = []
    await orders.subscribe_order_updates(lambda update: received.append(update))

    mock_conn.trade_ctx.set_handler.assert_called_once()
    handler = mock_conn.trade_ctx.set_handler.call_args.args[0]
    import moomoo as ft
    assert isinstance(handler, ft.TradeOrderHandlerBase)


async def test_subscribe_order_updates_dispatches_to_callback(mock_conn):
    import asyncio
    import moomoo as ft
    from unittest.mock import patch

    orders = Orders(mock_conn)
    received: list[dict] = []
    done = asyncio.Event()

    def callback(update):
        received.append(update)
        done.set()

    await orders.subscribe_order_updates(callback)

    handler = mock_conn.trade_ctx.set_handler.call_args.args[0]
    update_df = pd.DataFrame([{
        "order_id": "ORD001",
        "code": "US.AAPL",
        "trd_side": "BUY",
        "qty": 10,
        "price": 150.0,
        "filled_qty": 0,
        "order_status": "SUBMITTED",
        "updated_time": "2024-01-15 10:00:01",
        "create_time": "2024-01-15 10:00:00",
    }])

    with patch.object(ft.TradeOrderHandlerBase, "on_recv_rsp", return_value=(ft.RET_OK, update_df)):
        handler.on_recv_rsp(object())

    await asyncio.wait_for(done.wait(), timeout=1.0)
    assert received[0]["order_id"] == "ORD001"
    assert received[0]["symbol"] == "US.AAPL"
    assert received[0]["side"] == "BUY"
    assert received[0]["qty"] == 10
    assert received[0]["price"] == 150.0
    assert received[0]["filled_qty"] == 0
    assert received[0]["order_status"] == "SUBMITTED"
    assert received[0]["updated_at"] == "2024-01-15 10:00:01"
