import pandas as pd
import pytest
import moomoo as ft
from datetime import date
from unittest.mock import MagicMock
from connector.connection import ConnectionManager
from connector.options import Options
from connector.exceptions import MoomooOptionsError


@pytest.fixture
def mock_conn():
    conn = MagicMock(spec=ConnectionManager)
    conn.quote_ctx = MagicMock()
    return conn


def _option_snapshot_row(contract="US.AAPL240119C00150000"):
    """SDK column shape returned by get_market_snapshot for an option contract."""
    return {
        "code": contract,
        "last_price": 5.50,
        "bid_price": 5.40,
        "ask_price": 5.60,
        "volume": 1200,
        "option_open_interest": 8000,
        "option_implied_volatility": 0.25,
        "option_delta": 0.55,
        "option_gamma": 0.03,
        "option_theta": -0.05,
        "option_vega": 0.12,
        "option_strike_price": 150.0,
        "option_contract_size": 100.0,
    }


async def test_get_option_chain_returns_list(mock_conn):
    df = pd.DataFrame([{
        "code": "US.AAPL240119C00150000",
        "stock_name": "AAPL 240119 C 150",
        "option_type": "CALL",
        "strike_price": 150.0,
        "strike_time": "2024-01-19",
        "lot_size": 100,
    }])
    mock_conn.quote_ctx.get_option_chain.return_value = (ft.RET_OK, df)

    opts = Options(mock_conn)
    result = await opts.get_option_chain("AAPL", date(2024, 1, 19))

    assert len(result) == 1
    assert result[0]["contract"] == "US.AAPL240119C00150000"
    assert result[0]["option_type"] == "CALL"
    assert result[0]["strike_price"] == 150.0
    assert result[0]["expiry"] == "2024-01-19"
    assert result[0]["lot_size"] == 100


async def test_get_option_chain_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_option_chain.return_value = (ft.RET_ERROR, "Error")

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError):
        await opts.get_option_chain("AAPL", date(2024, 1, 19))


async def test_get_option_quote_returns_dict_with_greeks(mock_conn):
    df = pd.DataFrame([_option_snapshot_row()])
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_OK, df)

    opts = Options(mock_conn)
    result = await opts.get_option_quote("US.AAPL240119C00150000")

    assert result["contract"] == "US.AAPL240119C00150000"
    assert result["last_price"] == 5.50
    assert result["bid_price"] == 5.40
    assert result["ask_price"] == 5.60
    assert result["open_interest"] == 8000
    assert result["delta"] == 0.55
    assert result["implied_volatility"] == 0.25


async def test_get_option_quote_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_ERROR, "Error")

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError):
        await opts.get_option_quote("US.AAPL240119C00150000")


async def test_get_option_quote_raises_on_empty_response(mock_conn):
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_OK, pd.DataFrame())

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError, match="No snapshot data"):
        await opts.get_option_quote("US.AAPL240119C00150000")


async def test_get_greeks_returns_dict(mock_conn):
    df = pd.DataFrame([_option_snapshot_row()])
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_OK, df)

    opts = Options(mock_conn)
    result = await opts.get_greeks("US.AAPL240119C00150000")

    assert result["delta"] == 0.55
    assert result["gamma"] == 0.03
    assert result["theta"] == -0.05
    assert result["vega"] == 0.12
    assert result["implied_volatility"] == 0.25


async def test_get_greeks_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_ERROR, "Error")

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError):
        await opts.get_greeks("US.AAPL240119C00150000")


async def test_get_greeks_raises_on_empty_response(mock_conn):
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_OK, pd.DataFrame())

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError, match="No snapshot data"):
        await opts.get_greeks("US.AAPL240119C00150000")
