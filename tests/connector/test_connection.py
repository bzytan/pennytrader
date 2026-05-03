import asyncio
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


async def test_health_check_triggers_reconnect_on_bad_state(mock_quote_ctx, mock_trade_ctx):
    """Health loop reconnects when get_global_state returns non-OK."""
    mock_quote_ctx.get_global_state.return_value = (ft.RET_ERROR, None)

    with patch("connector.connection.ft.OpenQuoteContext", return_value=mock_quote_ctx), \
         patch("connector.connection.ft.OpenSecTradeContext", return_value=mock_trade_ctx), \
         patch("connector.connection.asyncio.sleep", return_value=None) as mock_sleep:

        conn = ConnectionManager()
        # Manually set up connected state to test health check in isolation
        conn._quote_ctx = mock_quote_ctx
        conn._trade_ctx = mock_trade_ctx
        conn._connected = True

        # Simulate one health check iteration (skip the 30s sleep, run get_global_state, expect reconnect attempt)
        with patch.object(conn, "_reconnect") as mock_reconnect:
            mock_reconnect.return_value = None
            # Run the health loop body once by patching sleep to raise after first call
            call_count = 0
            async def fake_sleep(n):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()
            with patch("connector.connection.asyncio.sleep", side_effect=fake_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await conn._health_check_loop()
            mock_reconnect.assert_called_once()


async def test_reconnect_retries_until_connected(mock_quote_ctx, mock_trade_ctx):
    """_reconnect retries with backoff until connection succeeds."""
    call_count = 0

    def make_contexts():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("OpenD not ready")
        return mock_quote_ctx, mock_trade_ctx

    with patch("connector.connection.ft.OpenQuoteContext") as MockQuote, \
         patch("connector.connection.ft.OpenSecTradeContext") as MockTrade, \
         patch("connector.connection.asyncio.sleep", return_value=None):

        def side_effect_quote(*args, **kwargs):
            return make_contexts()[0]
        def side_effect_trade(*args, **kwargs):
            return make_contexts()[1] if call_count >= 3 else (_ for _ in ()).throw(Exception("OpenD not ready"))

        conn = ConnectionManager()
        conn._quote_ctx = mock_quote_ctx
        conn._trade_ctx = mock_trade_ctx

        with patch.object(conn, "_connect_contexts") as mock_connect:
            attempt = 0
            async def fake_connect():
                nonlocal attempt
                attempt += 1
                if attempt < 3:
                    raise MoomooConnectionError("not ready")
                conn._connected = True
            mock_connect.side_effect = fake_connect
            await conn._reconnect()

        assert conn._connected is True
        assert mock_connect.call_count == 3
