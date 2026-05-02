import pytest

from connector.exceptions import (
    MoomooError,
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
        assert issubclass(cls, MoomooError)


def test_default_error_code_is_minus_one():
    exc = MoomooConnectionError("something went wrong")
    assert exc.error_code == -1


def test_can_be_raised_and_caught():
    with pytest.raises(MoomooConnectionError) as exc_info:
        raise MoomooConnectionError("boom", error_code=42)
    assert exc_info.value.error_code == 42
