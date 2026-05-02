# Moomoo Connector Design

## Overview

Build the core broker connector for pennytrader, providing async Python access to Moomoo's OpenD gateway for stock and options trading. This connector is the foundational layer the rest of the application will build on.

## Goals

- Connect to a locally running OpenD gateway in paper or live trading mode
- Expose async interfaces for market data, options data, account state, and order management
- Handle OpenD connection lifecycle including reconnection on drop
- Support both stock and options trading through a unified order interface

## Architecture

Domain modules with a shared `ConnectionManager` (Option B). The `ConnectionManager` handles the OpenD lifecycle and paper/live mode configuration. Each domain module receives the `ConnectionManager` as a dependency and uses it to access the underlying moomoo SDK context. No broker abstraction layer — this application is Moomoo-only.

## Project Structure

```
pennytrader/
├── connector/
│   ├── __init__.py
│   ├── connection.py      # ConnectionManager — OpenD lifecycle, paper/live switching
│   ├── exceptions.py      # Custom exception types
│   ├── market_data.py     # Stock quotes, price history, order book, real-time streams
│   ├── options.py         # Option chains, option quotes, Greeks
│   ├── account.py         # Positions (stocks + options), balances, account info
│   └── orders.py          # Place, cancel, modify, and query orders (stocks + options)
├── tests/
│   └── connector/
│       ├── test_connection.py
│       ├── test_market_data.py
│       ├── test_options.py
│       ├── test_account.py
│       └── test_orders.py
├── pyproject.toml
└── README.md
```

## Module Designs

### `connection.py` — ConnectionManager

Responsible for the full OpenD connection lifecycle.

**Configuration:**
- `mode`: `"paper"` or `"live"` — maps to moomoo SDK's `TrdEnv.SIMULATE` / `TrdEnv.REAL`
- `host`: OpenD host, default `"127.0.0.1"`
- `port`: OpenD port, default `11111`

**Responsibilities:**
- `connect()` — opens SDK connection to OpenD
- `disconnect()` — closes connection cleanly
- Reconnection with exponential backoff on connection drop
- Async health check loop that pings OpenD periodically and triggers reconnect on silence
- Context manager support (`async with ConnectionManager(...) as conn`)
- Exposes `trd_env` property so domain modules can pass the correct environment without knowing about paper/live themselves

### `market_data.py` — MarketData

Stock-specific market data. Receives a `ConnectionManager` instance.

**Methods:**
- `get_quote(symbol: str)` — current price, bid/ask, volume
- `get_price_history(symbol: str, start: date, end: date, interval: KLType)` — OHLCV candles
- `get_order_book(symbol: str)` — current bid/ask depth
- `subscribe_quotes(symbol: str, callback: Callable)` — real-time quote stream via SDK callback

### `options.py` — Options

Options-specific market data. Receives a `ConnectionManager` instance.

**Methods:**
- `get_option_chain(symbol: str, expiry: date)` — all strikes and contract details for an underlying at a given expiry
- `get_option_quote(contract: str)` — current price, bid/ask, open interest for a specific contract
- `get_greeks(contract: str)` — delta, gamma, theta, vega, implied volatility

### `account.py` — Account

Account state for both stock and options positions. Receives a `ConnectionManager` instance.

**Methods:**
- `get_positions()` — all current holdings; options positions include contract metadata (symbol, expiry, strike, call/put, contract size)
- `get_balance()` — cash, buying power, total assets
- `get_account_info()` — account ID, currency, environment (paper/live)

### `orders.py` — Orders

Order management for both stocks and options. Receives a `ConnectionManager` instance.

Options orders carry additional fields (expiry, strike, call/put, contract size). To avoid a sprawling parameter list, `place_order()` accepts an `OrderSpec` dataclass that covers both stock and options cases.

**Methods:**
- `place_order(spec: OrderSpec)` — submit a new order
- `cancel_order(order_id: str)` — cancel a pending order
- `modify_order(order_id: str, qty: int, price: float)` — change qty or price on a pending order
- `get_orders(status: OrderStatus)` — list orders filtered by status

**`OrderStatus` values:** `PENDING`, `FILLED`, `CANCELLED`, `FAILED`

**`OrderSpec` fields:**
- `symbol`, `qty`, `side` (buy/sell), `order_type` (limit/market), `price`
- Options-only (optional): `expiry`, `strike`, `option_type` (call/put), `contract_size`

## Error Handling

Custom exceptions live in `connector/exceptions.py` to avoid shadowing Python builtins. Each domain module maps moomoo SDK error codes to the appropriate type:

| Exception | Trigger |
|---|---|
| `MoomooConnectionError` | OpenD unreachable or connection dropped |
| `MoomooAuthenticationError` | Login or session failure |
| `MoomooOrderError` | Rejected order, invalid order parameters |
| `MoomooMarketDataError` | Symbol not found, data unavailable |
| `MoomooOptionsError` | Invalid contract, chain unavailable |

All exceptions carry the original SDK error code and message.

## Testing

Tests mock the moomoo SDK at the boundary — no live OpenD connection required.

- **`test_connection.py`** — connect/disconnect lifecycle, reconnect on drop, paper vs live mode, health check loop
- **`test_market_data.py`** — quote parsing, history intervals, order book depth, subscription callbacks
- **`test_options.py`** — chain parsing, Greeks extraction, quote parsing
- **`test_account.py`** — position parsing for stocks and options, balance fields, account info
- **`test_orders.py`** — order placement (stock and options), cancellation, modification, status filtering

**Stack:** `pytest` + `pytest-asyncio`

## Dependencies

- `moomoo-api` — official Moomoo Python SDK
- `pytest` + `pytest-asyncio` — testing
