import pytest
import moomoo as ft
from unittest.mock import MagicMock, patch
from connector.connection import ConnectionManager, TradingMode
from connector.exceptions import MoomooConnectionError


@pytest.fixture
def mock_quote_ctx():
    ctx = MagicMock()
    ctx.get_global_state.return_value = (ft.RET_OK, MagicMock())
    ctx.close.return_value = None
    return ctx


@pytest.fixture
def mock_trade_ctx():
    ctx = MagicMock()
    ctx.close.return_value = None
    return ctx


@pytest.fixture
def patched_sdk(mock_quote_ctx, mock_trade_ctx):
    with patch("connector.connection.ft.OpenQuoteContext", return_value=mock_quote_ctx), \
         patch("connector.connection.ft.OpenSecTradeContext", return_value=mock_trade_ctx):
        yield mock_quote_ctx, mock_trade_ctx


async def test_connect_paper_mode_sets_simulate_env(patched_sdk):
    conn = ConnectionManager(mode=TradingMode.PAPER)
    await conn.connect()
    assert conn.trd_env == ft.TrdEnv.SIMULATE
    assert conn._connected is True
    await conn.disconnect()


async def test_connect_live_mode_sets_real_env(patched_sdk):
    conn = ConnectionManager(mode=TradingMode.LIVE)
    await conn.connect()
    assert conn.trd_env == ft.TrdEnv.REAL
    await conn.disconnect()


async def test_disconnect_closes_contexts(patched_sdk, mock_quote_ctx, mock_trade_ctx):
    conn = ConnectionManager()
    await conn.connect()
    await conn.disconnect()
    mock_quote_ctx.close.assert_called_once()
    mock_trade_ctx.close.assert_called_once()
    assert conn._connected is False


async def test_quote_ctx_raises_when_not_connected():
    conn = ConnectionManager()
    with pytest.raises(MoomooConnectionError):
        _ = conn.quote_ctx


async def test_trade_ctx_raises_when_not_connected():
    conn = ConnectionManager()
    with pytest.raises(MoomooConnectionError):
        _ = conn.trade_ctx


async def test_context_manager(patched_sdk):
    async with ConnectionManager() as conn:
        assert conn._connected is True
    assert conn._connected is False


async def test_connect_raises_on_sdk_error():
    with patch("connector.connection.ft.OpenQuoteContext", side_effect=Exception("OpenD not running")):
        conn = ConnectionManager()
        with pytest.raises(MoomooConnectionError, match="OpenD not running"):
            await conn.connect()
