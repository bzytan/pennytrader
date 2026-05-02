import pandas as pd
import pytest
import moomoo as ft
from datetime import date
from unittest.mock import MagicMock
from connector.connection import ConnectionManager
from connector.market_data import MarketData
from connector.exceptions import MoomooMarketDataError


@pytest.fixture
def mock_conn():
    conn = MagicMock(spec=ConnectionManager)
    conn.quote_ctx = MagicMock()
    return conn


async def test_get_quote_returns_dict(mock_conn):
    df = pd.DataFrame([{
        "code": "US.AAPL",
        "last_price": 150.0,
        "open_price": 148.0,
        "high_price": 152.0,
        "low_price": 147.0,
        "volume": 1000000,
        "bid_price": 149.9,
        "ask_price": 150.1,
    }])
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_OK, df)

    md = MarketData(mock_conn)
    result = await md.get_quote("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["last_price"] == 150.0
    assert result["bid_price"] == 149.9
    assert result["ask_price"] == 150.1
    assert result["volume"] == 1000000


async def test_get_quote_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_ERROR, "Symbol not found")

    md = MarketData(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await md.get_quote("INVALID")


async def test_get_price_history_returns_list(mock_conn):
    df = pd.DataFrame([
        {"code": "US.AAPL", "time_key": "2024-01-02 00:00:00", "open": 185.0, "close": 186.0,
         "high": 187.0, "low": 184.0, "volume": 500000, "turnover": 92500000.0},
        {"code": "US.AAPL", "time_key": "2024-01-03 00:00:00", "open": 186.0, "close": 184.5,
         "high": 187.5, "low": 183.0, "volume": 600000, "turnover": 110700000.0},
    ])
    mock_conn.quote_ctx.request_history_kline.return_value = (ft.RET_OK, df, None)

    md = MarketData(mock_conn)
    result = await md.get_price_history("AAPL", date(2024, 1, 1), date(2024, 1, 31), ft.KLType.K_DAY)

    assert len(result) == 2
    assert result[0]["open"] == 185.0
    assert result[0]["close"] == 186.0
    assert result[1]["volume"] == 600000


async def test_get_price_history_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.request_history_kline.return_value = (ft.RET_ERROR, "Error", None)

    md = MarketData(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await md.get_price_history("AAPL", date(2024, 1, 1), date(2024, 1, 31), ft.KLType.K_DAY)


async def test_get_order_book_returns_bids_and_asks(mock_conn):
    bid_df = pd.DataFrame([{"price": 149.9, "volume": 100, "order_num": 3}])
    ask_df = pd.DataFrame([{"price": 150.1, "volume": 200, "order_num": 5}])
    mock_conn.quote_ctx.get_order_book.return_value = (ft.RET_OK, {"Bid": bid_df, "Ask": ask_df})

    md = MarketData(mock_conn)
    result = await md.get_order_book("AAPL")

    assert result["bids"][0]["price"] == 149.9
    assert result["bids"][0]["volume"] == 100
    assert result["asks"][0]["price"] == 150.1
    assert result["asks"][0]["volume"] == 200


async def test_get_order_book_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_order_book.return_value = (ft.RET_ERROR, "Error")

    md = MarketData(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await md.get_order_book("AAPL")


async def test_subscribe_quotes_registers_handler(mock_conn):
    mock_conn.quote_ctx.subscribe.return_value = (ft.RET_OK, "")

    received = []
    md = MarketData(mock_conn)
    await md.subscribe_quotes("AAPL", lambda data: received.append(data))

    mock_conn.quote_ctx.set_handler.assert_called_once()
    mock_conn.quote_ctx.subscribe.assert_called_once()
    # Verify the subscription task was stored
    assert len(md._subscription_tasks) == 1
