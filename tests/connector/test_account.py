import pandas as pd
import pytest
import moomoo as ft
from unittest.mock import MagicMock
from connector.connection import ConnectionManager
from connector.account import Account
from connector.exceptions import MoomooMarketDataError


@pytest.fixture
def mock_conn():
    conn = MagicMock(spec=ConnectionManager)
    conn.trade_ctx = MagicMock()
    conn.trd_env = ft.TrdEnv.SIMULATE
    return conn


async def test_get_positions_returns_stock_positions(mock_conn):
    df = pd.DataFrame([{
        "code": "US.AAPL",
        "stock_name": "Apple Inc.",
        "qty": 10,
        "cost_price": 145.0,
        "market_val": 1500.0,
        "nominal_price": 150.0,
        "pl_val": 50.0,
        "currency": "USD",
        "position_side": "LONG",
    }])
    mock_conn.trade_ctx.position_list_query.return_value = (ft.RET_OK, df)

    acct = Account(mock_conn)
    result = await acct.get_positions()

    assert len(result) == 1
    assert result[0]["symbol"] == "US.AAPL"
    assert result[0]["qty"] == 10
    assert result[0]["cost_price"] == 145.0
    assert result[0]["market_value"] == 1500.0
    assert result[0]["is_option"] is False


async def test_get_positions_flags_options(mock_conn):
    df = pd.DataFrame([{
        "code": "US.AAPL240119C00150000",
        "stock_name": "AAPL 240119 C 150",
        "qty": 2,
        "cost_price": 5.0,
        "market_val": 1100.0,
        "nominal_price": 5.50,
        "pl_val": 100.0,
        "currency": "USD",
        "position_side": "LONG",
    }])
    mock_conn.trade_ctx.position_list_query.return_value = (ft.RET_OK, df)

    acct = Account(mock_conn)
    result = await acct.get_positions()

    assert result[0]["is_option"] is True
    assert result[0]["symbol"] == "US.AAPL240119C00150000"


async def test_get_positions_raises_on_sdk_error(mock_conn):
    mock_conn.trade_ctx.position_list_query.return_value = (ft.RET_ERROR, "Error")

    acct = Account(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await acct.get_positions()


async def test_get_balance_returns_dict(mock_conn):
    df = pd.DataFrame([{
        "cash": 10000.0,
        "power": 20000.0,
        "total_assets": 30000.0,
        "market_val": 15000.0,
        "currency": "USD",
    }])
    mock_conn.trade_ctx.accinfo_query.return_value = (ft.RET_OK, df)

    acct = Account(mock_conn)
    result = await acct.get_balance()

    assert result["cash"] == 10000.0
    assert result["buying_power"] == 20000.0
    assert result["total_assets"] == 30000.0
    assert result["currency"] == "USD"


async def test_get_balance_raises_on_sdk_error(mock_conn):
    mock_conn.trade_ctx.accinfo_query.return_value = (ft.RET_ERROR, "Error")

    acct = Account(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await acct.get_balance()


async def test_get_balance_raises_on_empty_response(mock_conn):
    mock_conn.trade_ctx.accinfo_query.return_value = (ft.RET_OK, pd.DataFrame())

    acct = Account(mock_conn)
    with pytest.raises(MoomooMarketDataError, match="No balance data"):
        await acct.get_balance()


async def test_get_account_info_returns_paper_environment(mock_conn):
    df = pd.DataFrame([
        {"acc_id": "99999999", "currency": "USD", "acc_type": "MARGIN",
         "trd_env": ft.TrdEnv.REAL},
        {"acc_id": "12345678", "currency": "USD", "acc_type": "MARGIN",
         "trd_env": ft.TrdEnv.SIMULATE},
    ])
    mock_conn.trade_ctx.get_acc_list.return_value = (ft.RET_OK, df)

    acct = Account(mock_conn)
    result = await acct.get_account_info()

    assert result["account_id"] == "12345678"  # paper, not the real one
    assert result["currency"] == "USD"
    assert result["environment"] == "paper"


async def test_get_account_info_raises_on_sdk_error(mock_conn):
    mock_conn.trade_ctx.get_acc_list.return_value = (ft.RET_ERROR, "Error")

    acct = Account(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await acct.get_account_info()


async def test_get_account_info_raises_on_empty_response(mock_conn):
    mock_conn.trade_ctx.get_acc_list.return_value = (ft.RET_OK, pd.DataFrame())

    acct = Account(mock_conn)
    with pytest.raises(MoomooMarketDataError, match="No account data"):
        await acct.get_account_info()
