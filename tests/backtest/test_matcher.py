from datetime import datetime

import pytest

from backtest.matcher import OrderMatcher, PendingOrder


def _bar(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close,
            "volume": 1000, "time": datetime(2026, 1, 15, 9, 31)}


def test_limit_buy_fills_when_bar_low_crosses():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                         qty=10, order_type="LIMIT", limit_price=100.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 102, 99.5, 100.5))
    assert len(fills) == 1
    assert fills[0]["price"] == 100.0
    assert fills[0]["qty"] == 10


def test_limit_buy_does_not_fill_when_bar_low_above_limit():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                         qty=10, order_type="LIMIT", limit_price=100.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 102, 100.5, 101.5))
    assert fills == []


def test_limit_sell_fills_when_bar_high_crosses():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="SELL",
                         qty=10, order_type="LIMIT", limit_price=105.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 105.5, 100, 102))
    assert fills[0]["price"] == 105.0


def test_limit_sell_does_not_fill_when_bar_high_below_limit():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="SELL",
                         qty=10, order_type="LIMIT", limit_price=105.0)
    fills = matcher.process_bar(orders=[order], bar=_bar(101, 104, 100, 102))
    assert fills == []


def test_market_buy_fills_at_bar_open():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                         qty=5, order_type="MARKET", limit_price=None)
    fills = matcher.process_bar(orders=[order], bar=_bar(101.25, 102, 100, 101.5))
    assert fills[0]["price"] == 101.25
    assert fills[0]["qty"] == 5


def test_market_sell_fills_at_bar_open():
    matcher = OrderMatcher()
    order = PendingOrder(order_id="O1", symbol="AAPL", side="SELL",
                         qty=5, order_type="MARKET", limit_price=None)
    fills = matcher.process_bar(orders=[order], bar=_bar(101.25, 102, 100, 101.5))
    assert fills[0]["price"] == 101.25


def test_multiple_orders_processed_independently():
    matcher = OrderMatcher()
    o1 = PendingOrder(order_id="O1", symbol="AAPL", side="BUY",
                      qty=10, order_type="LIMIT", limit_price=99.0)
    o2 = PendingOrder(order_id="O2", symbol="AAPL", side="BUY",
                      qty=5, order_type="LIMIT", limit_price=100.5)
    fills = matcher.process_bar(orders=[o1, o2], bar=_bar(101, 102, 100, 101.5))
    assert len(fills) == 1
    assert fills[0]["order_id"] == "O2"
