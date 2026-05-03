import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from connector.exceptions import MoomooOrderError
from engine.executor import ProposalExecutor


@pytest.fixture
def safe_orders():
    so = MagicMock()
    so.place_order = AsyncMock(return_value="ORD001")
    so.cancel_order = AsyncMock()
    so.modify_order = AsyncMock()
    return so


async def test_executor_places_order_proposal(tmp_path, safe_orders):
    proposals = tmp_path / "proposed_trades.jsonl"
    proposals.write_text(json.dumps({
        "action": "place_order",
        "spec": {"symbol": "AAPL", "qty": 10, "side": "buy",
                 "order_type": "limit", "price": 150.0},
    }) + "\n")
    executor = ProposalExecutor(safe_orders=safe_orders)
    results = await executor.execute(proposals)
    assert len(results) == 1
    assert results[0]["status"] == "placed"
    assert results[0]["order_id"] == "ORD001"
    safe_orders.place_order.assert_awaited_once()


async def test_executor_records_safeorders_rejection(tmp_path, safe_orders):
    safe_orders.place_order = AsyncMock(
        side_effect=MoomooOrderError("exceeds max position size", error_code=-1)
    )
    proposals = tmp_path / "proposed_trades.jsonl"
    proposals.write_text(json.dumps({
        "action": "place_order",
        "spec": {"symbol": "AAPL", "qty": 1000, "side": "buy",
                 "order_type": "limit", "price": 150.0},
    }) + "\n")
    executor = ProposalExecutor(safe_orders=safe_orders)
    results = await executor.execute(proposals)
    assert results[0]["status"] == "rejected"
    assert "exceeds max position size" in results[0]["error"]


async def test_executor_handles_cancel_and_modify(tmp_path, safe_orders):
    proposals = tmp_path / "proposed_trades.jsonl"
    proposals.write_text(
        json.dumps({"action": "cancel_order", "order_id": "ORD001"}) + "\n"
        + json.dumps({"action": "modify_order", "order_id": "ORD002",
                      "qty": 5, "price": 155.0}) + "\n"
    )
    executor = ProposalExecutor(safe_orders=safe_orders)
    results = await executor.execute(proposals)
    assert results[0]["status"] == "cancelled"
    assert results[1]["status"] == "modified"


async def test_executor_records_parse_error(tmp_path, safe_orders):
    proposals = tmp_path / "proposed_trades.jsonl"
    proposals.write_text("not-json\n")
    executor = ProposalExecutor(safe_orders=safe_orders)
    results = await executor.execute(proposals)
    assert results[0]["status"] == "parse_error"


async def test_executor_consumes_proposals_file(tmp_path, safe_orders):
    proposals = tmp_path / "proposed_trades.jsonl"
    proposals.write_text(json.dumps({
        "action": "place_order",
        "spec": {"symbol": "AAPL", "qty": 1, "side": "buy",
                 "order_type": "limit", "price": 150.0},
    }) + "\n")
    executor = ProposalExecutor(safe_orders=safe_orders)
    await executor.execute(proposals)
    assert not proposals.exists()


async def test_executor_returns_empty_when_no_proposals(tmp_path, safe_orders):
    proposals = tmp_path / "proposed_trades.jsonl"
    executor = ProposalExecutor(safe_orders=safe_orders)
    results = await executor.execute(proposals)
    assert results == []
    safe_orders.place_order.assert_not_awaited()


async def test_executor_handles_option_proposal(tmp_path, safe_orders):
    proposals = tmp_path / "proposed_trades.jsonl"
    proposals.write_text(json.dumps({
        "action": "place_order",
        "spec": {
            "symbol": "US.AAPL240119C00150000", "qty": 1, "side": "buy",
            "order_type": "limit", "price": 5.50,
            "expiry": "2024-01-19", "strike": 150.0,
            "option_type": "call", "contract_size": 100,
        },
    }) + "\n")
    executor = ProposalExecutor(safe_orders=safe_orders)
    results = await executor.execute(proposals)
    assert results[0]["status"] == "placed"
