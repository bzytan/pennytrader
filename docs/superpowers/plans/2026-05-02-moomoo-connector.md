# Moomoo Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Moomoo broker connector for pennytrader with async interfaces for market data, options, account state, and order management.

**Architecture:** Domain modules share a `ConnectionManager` that owns the OpenD connection lifecycle. All moomoo SDK calls are synchronous and are wrapped with `asyncio.run_in_executor` to provide an async interface. Paper/live mode is set once on `ConnectionManager` via `TradingMode` and exposed through its `trd_env` property.

**Tech Stack:** Python 3.11+, moomoo-api, pytest, pytest-asyncio

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Create | Project metadata and dependencies |
| `connector/__init__.py` | Create | Package marker |
| `tests/__init__.py` | Create | Test package marker |
| `tests/connector/__init__.py` | Create | Test subpackage marker |
| `connector/exceptions.py` | Create | Custom Moomoo exception types |
| `connector/connection.py` | Create | ConnectionManager — OpenD lifecycle, paper/live mode |
| `connector/market_data.py` | Create | Stock quotes, history, order book, subscriptions |
| `connector/options.py` | Create | Option chains, quotes, Greeks |
| `connector/account.py` | Create | Positions, balance, account info |
| `connector/orders.py` | Create | OrderSpec, OrderStatus, order management |
| `tests/connector/test_exceptions.py` | Create | Exception type tests |
| `tests/connector/test_connection.py` | Create | ConnectionManager tests |
| `tests/connector/test_market_data.py` | Create | MarketData tests |
| `tests/connector/test_options.py` | Create | Options tests |
| `tests/connector/test_account.py` | Create | Account tests |
| `tests/connector/test_orders.py` | Create | Orders tests |

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `connector/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/connector/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "pennytrader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "moomoo-api>=6.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["."]
include = ["connector*"]
```

- [ ] **Step 2: Create package init files**

```bash
mkdir -p connector tests/connector
touch connector/__init__.py tests/__init__.py tests/connector/__init__.py
```

- [ ] **Step 3: Install dependencies**

```bash
pip install moomoo-api pytest pytest-asyncio
```

Expected: packages install without errors.

- [ ] **Step 4: Verify pytest discovers tests**

```bash
pytest tests/ --collect-only
```

Expected: "no tests ran" with no errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml connector/__init__.py tests/__init__.py tests/connector/__init__.py
git commit -m "chore: scaffold project structure"
```

---

### Task 2: Custom exceptions

**Files:**
- Create: `connector/exceptions.py`
- Create: `tests/connector/test_exceptions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/connector/test_exceptions.py`:

```python
from connector.exceptions import (
    MoomooConnectionError,
    MoomooAuthenticationError,
    MoomooOrderError,
    MoomooMarketDataError,
    MoomooOptionsError,
)


def test_connection_error_carries_code():
    exc = MoomooConnectionError("OpenD not running", error_code=-1)
    assert str(exc) == "OpenD not running"
    assert exc.error_code == -1


def test_authentication_error_carries_code():
    exc = MoomooAuthenticationError("Login failed", error_code=-2)
    assert str(exc) == "Login failed"
    assert exc.error_code == -2


def test_order_error_carries_code():
    exc = MoomooOrderError("Order rejected", error_code=-3)
    assert str(exc) == "Order rejected"
    assert exc.error_code == -3


def test_market_data_error_carries_code():
    exc = MoomooMarketDataError("Symbol not found", error_code=-4)
    assert str(exc) == "Symbol not found"
    assert exc.error_code == -4


def test_options_error_carries_code():
    exc = MoomooOptionsError("Invalid contract", error_code=-5)
    assert str(exc) == "Invalid contract"
    assert exc.error_code == -5


def test_all_are_exception_subclasses():
    for cls in [
        MoomooConnectionError,
        MoomooAuthenticationError,
        MoomooOrderError,
        MoomooMarketDataError,
        MoomooOptionsError,
    ]:
        assert issubclass(cls, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/connector/test_exceptions.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'connector.exceptions'`

- [ ] **Step 3: Write the implementation**

Create `connector/exceptions.py`:

```python
class MoomooConnectionError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooAuthenticationError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooOrderError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooMarketDataError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooOptionsError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/connector/test_exceptions.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add connector/exceptions.py tests/connector/test_exceptions.py
git commit -m "feat: add custom Moomoo exception types"
```

---

### Task 3: ConnectionManager

**Files:**
- Create: `connector/connection.py`
- Create: `tests/connector/test_connection.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/connector/test_connection.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/connector/test_connection.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'connector.connection'`

- [ ] **Step 3: Write the implementation**

Create `connector/connection.py`:

```python
import asyncio
import contextlib
from enum import Enum

import moomoo as ft

from .exceptions import MoomooConnectionError


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class ConnectionManager:
    def __init__(
        self,
        mode: TradingMode = TradingMode.PAPER,
        host: str = "127.0.0.1",
        port: int = 11111,
    ) -> None:
        self.mode = mode
        self.host = host
        self.port = port
        self._quote_ctx: ft.OpenQuoteContext | None = None
        self._trade_ctx: ft.OpenSecTradeContext | None = None
        self._health_task: asyncio.Task | None = None
        self._connected: bool = False

    @property
    def trd_env(self) -> ft.TrdEnv:
        return ft.TrdEnv.SIMULATE if self.mode == TradingMode.PAPER else ft.TrdEnv.REAL

    @property
    def quote_ctx(self) -> ft.OpenQuoteContext:
        if self._quote_ctx is None:
            raise MoomooConnectionError("Not connected to OpenD")
        return self._quote_ctx

    @property
    def trade_ctx(self) -> ft.OpenSecTradeContext:
        if self._trade_ctx is None:
            raise MoomooConnectionError("Not connected to OpenD")
        return self._trade_ctx

    async def connect(self) -> None:
        await self._connect_contexts()
        self._health_task = asyncio.create_task(self._health_check_loop())

    async def disconnect(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None

        loop = asyncio.get_running_loop()
        if self._quote_ctx:
            await loop.run_in_executor(None, self._quote_ctx.close)
            self._quote_ctx = None
        if self._trade_ctx:
            await loop.run_in_executor(None, self._trade_ctx.close)
            self._trade_ctx = None
        self._connected = False

    async def _connect_contexts(self) -> None:
        loop = asyncio.get_running_loop()

        def _make_contexts() -> tuple[ft.OpenQuoteContext, ft.OpenSecTradeContext]:
            quote_ctx = ft.OpenQuoteContext(host=self.host, port=self.port)
            trade_ctx = ft.OpenSecTradeContext(
                host=self.host,
                port=self.port,
                security_firm=ft.SecurityFirm.FUTUINC,
                trd_env=self.trd_env,
            )
            return quote_ctx, trade_ctx

        try:
            self._quote_ctx, self._trade_ctx = await loop.run_in_executor(None, _make_contexts)
            self._connected = True
        except Exception as e:
            raise MoomooConnectionError(str(e)) from e

    async def _health_check_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                loop = asyncio.get_running_loop()
                ret, _ = await loop.run_in_executor(None, self._quote_ctx.get_global_state)
                if ret != ft.RET_OK:
                    await self._reconnect()
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._reconnect()

    async def _reconnect(self) -> None:
        self._connected = False
        loop = asyncio.get_running_loop()
        for ctx in (self._quote_ctx, self._trade_ctx):
            if ctx:
                with contextlib.suppress(Exception):
                    await loop.run_in_executor(None, ctx.close)
        self._quote_ctx = None
        self._trade_ctx = None

        backoff = 1
        while not self._connected:
            try:
                await self._connect_contexts()
            except MoomooConnectionError:
                await asyncio.sleep(min(backoff, 64))
                backoff = min(backoff * 2, 64)

    async def __aenter__(self) -> "ConnectionManager":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/connector/test_connection.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add connector/connection.py tests/connector/test_connection.py
git commit -m "feat: add ConnectionManager with OpenD lifecycle and reconnection"
```

---

### Task 4: MarketData

**Files:**
- Create: `connector/market_data.py`
- Create: `tests/connector/test_market_data.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/connector/test_market_data.py`:

```python
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

    md = MarketData(mock_conn)
    await md.subscribe_quotes("AAPL", lambda data: None)

    mock_conn.quote_ctx.set_handler.assert_called_once()
    mock_conn.quote_ctx.subscribe.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/connector/test_market_data.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'connector.market_data'`

- [ ] **Step 3: Write the implementation**

Create `connector/market_data.py`:

```python
import asyncio
from collections.abc import Callable
from datetime import date

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooMarketDataError


class MarketData:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    async def get_quote(self, symbol: str) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_market_snapshot([f"US.{symbol}"]),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        row = data.iloc[0]
        return {
            "symbol": symbol,
            "last_price": float(row["last_price"]),
            "open_price": float(row["open_price"]),
            "high_price": float(row["high_price"]),
            "low_price": float(row["low_price"]),
            "volume": int(row["volume"]),
            "bid_price": float(row["bid_price"]),
            "ask_price": float(row["ask_price"]),
        }

    async def get_price_history(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: ft.KLType,
    ) -> list[dict]:
        loop = asyncio.get_running_loop()
        ret, data, _ = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.request_history_kline(
                f"US.{symbol}",
                start=start.isoformat(),
                end=end.isoformat(),
                ktype=interval,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        return [
            {
                "time": row["time_key"],
                "open": float(row["open"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "volume": int(row["volume"]),
                "turnover": float(row["turnover"]),
            }
            for _, row in data.iterrows()
        ]

    async def get_order_book(self, symbol: str) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_order_book(f"US.{symbol}"),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        return {
            "bids": [
                {"price": float(row["price"]), "volume": int(row["volume"])}
                for _, row in data["Bid"].iterrows()
            ],
            "asks": [
                {"price": float(row["price"]), "volume": int(row["volume"])}
                for _, row in data["Ask"].iterrows()
            ],
        }

    async def subscribe_quotes(self, symbol: str, callback: Callable[[dict], None]) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        class _Handler(ft.QuoteHandlerBase):
            def on_recv_rsp(self, rsp_str: str) -> tuple:
                ret_code, content = super().on_recv_rsp(rsp_str)
                if ret_code == ft.RET_OK and not content.empty:
                    row = content.iloc[0]
                    loop.call_soon_threadsafe(queue.put_nowait, {
                        "symbol": symbol,
                        "last_price": float(row["last_price"]),
                        "bid_price": float(row["bid_price"]),
                        "ask_price": float(row["ask_price"]),
                        "volume": int(row["volume"]),
                    })
                return ret_code, content

        quote_ctx = self._conn.quote_ctx
        quote_ctx.set_handler(_Handler())
        await loop.run_in_executor(
            None,
            lambda: quote_ctx.subscribe([f"US.{symbol}"], [ft.SubType.QUOTE]),
        )
        asyncio.create_task(self._dispatch(queue, callback))

    @staticmethod
    async def _dispatch(queue: asyncio.Queue, callback: Callable[[dict], None]) -> None:
        while True:
            data = await queue.get()
            callback(data)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/connector/test_market_data.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add connector/market_data.py tests/connector/test_market_data.py
git commit -m "feat: add MarketData module for quotes, history, order book, and subscriptions"
```

---

### Task 5: Options

**Files:**
- Create: `connector/options.py`
- Create: `tests/connector/test_options.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/connector/test_options.py`:

```python
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


async def test_get_option_chain_returns_list(mock_conn):
    df = pd.DataFrame([{
        "code": "US.AAPL240119C00150000",
        "stock_name": "AAPL 240119 C 150",
        "option_type": "CALL",
        "strike_price": 150.0,
        "strike_time": "2024-01-19",
        "lot_size": 100,
        "implied_volatility": 0.25,
        "delta": 0.55,
        "gamma": 0.03,
        "theta": -0.05,
        "vega": 0.12,
    }])
    mock_conn.quote_ctx.get_option_chain.return_value = (ft.RET_OK, df)

    opts = Options(mock_conn)
    result = await opts.get_option_chain("AAPL", date(2024, 1, 19))

    assert len(result) == 1
    assert result[0]["contract"] == "US.AAPL240119C00150000"
    assert result[0]["option_type"] == "CALL"
    assert result[0]["strike_price"] == 150.0
    assert result[0]["expiry"] == "2024-01-19"


async def test_get_option_chain_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_option_chain.return_value = (ft.RET_ERROR, "Error")

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError):
        await opts.get_option_chain("AAPL", date(2024, 1, 19))


async def test_get_option_quote_returns_dict(mock_conn):
    df = pd.DataFrame([{
        "code": "US.AAPL240119C00150000",
        "last_price": 5.50,
        "bid_price": 5.40,
        "ask_price": 5.60,
        "volume": 1200,
        "open_interest": 8000,
    }])
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_OK, df)

    opts = Options(mock_conn)
    result = await opts.get_option_quote("US.AAPL240119C00150000")

    assert result["contract"] == "US.AAPL240119C00150000"
    assert result["last_price"] == 5.50
    assert result["bid_price"] == 5.40
    assert result["ask_price"] == 5.60
    assert result["open_interest"] == 8000


async def test_get_option_quote_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_market_snapshot.return_value = (ft.RET_ERROR, "Error")

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError):
        await opts.get_option_quote("US.AAPL240119C00150000")


async def test_get_greeks_returns_dict(mock_conn):
    df = pd.DataFrame([{
        "code": "US.AAPL240119C00150000",
        "option_type": "CALL",
        "strike_price": 150.0,
        "strike_time": "2024-01-19",
        "lot_size": 100,
        "implied_volatility": 0.25,
        "delta": 0.55,
        "gamma": 0.03,
        "theta": -0.05,
        "vega": 0.12,
    }])
    mock_conn.quote_ctx.get_option_chain.return_value = (ft.RET_OK, df)

    opts = Options(mock_conn)
    result = await opts.get_greeks("US.AAPL240119C00150000")

    assert result["delta"] == 0.55
    assert result["gamma"] == 0.03
    assert result["theta"] == -0.05
    assert result["vega"] == 0.12
    assert result["implied_volatility"] == 0.25


async def test_get_greeks_raises_on_sdk_error(mock_conn):
    mock_conn.quote_ctx.get_option_chain.return_value = (ft.RET_ERROR, "Error")

    opts = Options(mock_conn)
    with pytest.raises(MoomooOptionsError):
        await opts.get_greeks("US.AAPL240119C00150000")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/connector/test_options.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'connector.options'`

- [ ] **Step 3: Write the implementation**

Create `connector/options.py`:

```python
import asyncio
import re
from datetime import date

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooOptionsError


def _parse_expiry_from_contract(contract: str) -> date:
    """Extract expiry from OCC-style contract code e.g. US.AAPL240119C00150000 → 2024-01-19."""
    match = re.search(r'(\d{6})[CP]', contract)
    if not match:
        raise MoomooOptionsError(f"Cannot parse expiry from contract: {contract}")
    raw = match.group(1)
    return date(2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:6]))


def _parse_underlying_from_contract(contract: str) -> str:
    """Extract underlying symbol from contract code e.g. US.AAPL240119C00150000 → AAPL."""
    match = re.search(r'US\.([A-Z]+)\d', contract)
    if not match:
        raise MoomooOptionsError(f"Cannot parse underlying from contract: {contract}")
    return match.group(1)


class Options:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    async def get_option_chain(self, symbol: str, expiry: date) -> list[dict]:
        loop = asyncio.get_running_loop()
        expiry_str = expiry.isoformat()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_option_chain(
                code=f"US.{symbol}",
                start=expiry_str,
                end=expiry_str,
                option_type=ft.OptionType.ALL,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOptionsError(str(data), error_code=ret)
        return [
            {
                "contract": row["code"],
                "option_type": row["option_type"],
                "strike_price": float(row["strike_price"]),
                "expiry": row["strike_time"],
                "lot_size": int(row["lot_size"]),
                "implied_volatility": float(row["implied_volatility"]),
                "delta": float(row["delta"]),
                "gamma": float(row["gamma"]),
                "theta": float(row["theta"]),
                "vega": float(row["vega"]),
            }
            for _, row in data.iterrows()
        ]

    async def get_option_quote(self, contract: str) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.quote_ctx.get_market_snapshot([contract]),
        )
        if ret != ft.RET_OK:
            raise MoomooOptionsError(str(data), error_code=ret)
        row = data.iloc[0]
        return {
            "contract": contract,
            "last_price": float(row["last_price"]),
            "bid_price": float(row["bid_price"]),
            "ask_price": float(row["ask_price"]),
            "volume": int(row["volume"]),
            "open_interest": int(row["open_interest"]),
        }

    async def get_greeks(self, contract: str) -> dict:
        underlying = _parse_underlying_from_contract(contract)
        expiry = _parse_expiry_from_contract(contract)
        chain = await self.get_option_chain(underlying, expiry)
        for entry in chain:
            if entry["contract"] == contract:
                return {
                    "delta": entry["delta"],
                    "gamma": entry["gamma"],
                    "theta": entry["theta"],
                    "vega": entry["vega"],
                    "implied_volatility": entry["implied_volatility"],
                }
        raise MoomooOptionsError(f"Contract not found in chain: {contract}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/connector/test_options.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add connector/options.py tests/connector/test_options.py
git commit -m "feat: add Options module for chains, quotes, and Greeks"
```

---

### Task 6: Account

**Files:**
- Create: `connector/account.py`
- Create: `tests/connector/test_account.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/connector/test_account.py`:

```python
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


async def test_get_account_info_returns_paper_environment(mock_conn):
    df = pd.DataFrame([{
        "acc_id": "12345678",
        "currency": "USD",
        "acc_type": "MARGIN",
    }])
    mock_conn.trade_ctx.get_acc_list.return_value = (ft.RET_OK, df)

    acct = Account(mock_conn)
    result = await acct.get_account_info()

    assert result["account_id"] == "12345678"
    assert result["currency"] == "USD"
    assert result["environment"] == "paper"


async def test_get_account_info_raises_on_sdk_error(mock_conn):
    mock_conn.trade_ctx.get_acc_list.return_value = (ft.RET_ERROR, "Error")

    acct = Account(mock_conn)
    with pytest.raises(MoomooMarketDataError):
        await acct.get_account_info()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/connector/test_account.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'connector.account'`

- [ ] **Step 3: Write the implementation**

Create `connector/account.py`:

```python
import asyncio
import re

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooMarketDataError


def _is_option_code(code: str) -> bool:
    return bool(re.search(r'\d{6}[CP]', code))


class Account:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    async def get_positions(self) -> list[dict]:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.position_list_query(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        return [
            {
                "symbol": row["code"],
                "name": row["stock_name"],
                "qty": int(row["qty"]),
                "cost_price": float(row["cost_price"]),
                "market_value": float(row["market_val"]),
                "current_price": float(row["nominal_price"]),
                "unrealized_pl": float(row["pl_val"]),
                "currency": row["currency"],
                "side": row["position_side"],
                "is_option": _is_option_code(row["code"]),
            }
            for _, row in data.iterrows()
        ]

    async def get_balance(self) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.accinfo_query(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        row = data.iloc[0]
        return {
            "cash": float(row["cash"]),
            "buying_power": float(row["power"]),
            "total_assets": float(row["total_assets"]),
            "market_value": float(row["market_val"]),
            "currency": row["currency"],
        }

    async def get_account_info(self) -> dict:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.get_acc_list(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooMarketDataError(str(data), error_code=ret)
        row = data.iloc[0]
        env = "paper" if self._conn.trd_env == ft.TrdEnv.SIMULATE else "live"
        return {
            "account_id": str(row["acc_id"]),
            "currency": row["currency"],
            "environment": env,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/connector/test_account.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add connector/account.py tests/connector/test_account.py
git commit -m "feat: add Account module for positions, balance, and account info"
```

---

### Task 7: Orders

**Files:**
- Create: `connector/orders.py`
- Create: `tests/connector/test_orders.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/connector/test_orders.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/connector/test_orders.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'connector.orders'`

- [ ] **Step 3: Write the implementation**

Create `connector/orders.py`:

```python
import asyncio
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

import moomoo as ft

from .connection import ConnectionManager
from .exceptions import MoomooOrderError


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


_MOOMOO_STATUS_MAP: dict[str, OrderStatus] = {
    "SUBMITTING": OrderStatus.PENDING,
    "SUBMITTED": OrderStatus.PENDING,
    "FILLED_PART": OrderStatus.PENDING,
    "FILLED_ALL": OrderStatus.FILLED,
    "CANCELLED_PART": OrderStatus.CANCELLED,
    "CANCELLED_ALL": OrderStatus.CANCELLED,
    "FAILED": OrderStatus.FAILED,
    "DISABLED": OrderStatus.FAILED,
    "DELETED": OrderStatus.CANCELLED,
}

_TRADE_SIDE_MAP: dict[TradeSide, ft.TrdSide] = {
    TradeSide.BUY: ft.TrdSide.BUY,
    TradeSide.SELL: ft.TrdSide.SELL,
}

_ORDER_TYPE_MAP: dict[OrderType, ft.OrderType] = {
    OrderType.LIMIT: ft.OrderType.NORMAL,
    OrderType.MARKET: ft.OrderType.MARKET,
}


@dataclass
class OrderSpec:
    symbol: str
    qty: int
    side: TradeSide
    order_type: OrderType
    price: float
    expiry: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[OptionType] = None
    contract_size: Optional[int] = None

    @property
    def is_option(self) -> bool:
        return self.expiry is not None


class Orders:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    async def place_order(self, spec: OrderSpec) -> str:
        loop = asyncio.get_running_loop()
        code = spec.symbol if spec.is_option else f"US.{spec.symbol}"
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.place_order(
                price=spec.price,
                qty=spec.qty,
                code=code,
                trd_side=_TRADE_SIDE_MAP[spec.side],
                order_type=_ORDER_TYPE_MAP[spec.order_type],
                trd_env=self._conn.trd_env,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)
        return str(data.iloc[0]["order_id"])

    async def cancel_order(self, order_id: str) -> None:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.modify_order(
                modify_order_op=ft.ModifyOrderOp.CANCEL,
                order_id=order_id,
                qty=0,
                price=0,
                trd_env=self._conn.trd_env,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)

    async def modify_order(self, order_id: str, qty: int, price: float) -> None:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.modify_order(
                modify_order_op=ft.ModifyOrderOp.NORMAL,
                order_id=order_id,
                qty=qty,
                price=price,
                trd_env=self._conn.trd_env,
            ),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)

    async def get_orders(self, status: OrderStatus) -> list[dict]:
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._conn.trade_ctx.order_list_query(trd_env=self._conn.trd_env),
        )
        if ret != ft.RET_OK:
            raise MoomooOrderError(str(data), error_code=ret)
        results = []
        for _, row in data.iterrows():
            mapped_status = _MOOMOO_STATUS_MAP.get(row["order_status"], OrderStatus.FAILED)
            if mapped_status == status:
                results.append({
                    "order_id": str(row["order_id"]),
                    "symbol": row["code"],
                    "name": row["stock_name"],
                    "side": row["trd_side"],
                    "order_type": row["order_type"],
                    "price": float(row["price"]),
                    "qty": int(row["qty"]),
                    "filled_qty": int(row["filled_qty"]),
                    "avg_fill_price": float(row["avg_fill_price"]),
                    "status": mapped_status,
                    "created_at": row["create_time"],
                })
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/connector/test_orders.py -v
```

Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add connector/orders.py tests/connector/test_orders.py
git commit -m "feat: add Orders module with OrderSpec, OrderStatus, and order management"
```

---

### Task 8: Final integration check

**Files:** None — verification only

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests pass across all modules, no warnings.

- [ ] **Step 2: Verify package imports cleanly**

```bash
python -c "
from connector.connection import ConnectionManager, TradingMode
from connector.market_data import MarketData
from connector.options import Options
from connector.account import Account
from connector.orders import Orders, OrderSpec, OrderStatus, TradeSide, OrderType, OptionType
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore: verify full connector package"
```
