import json
from pathlib import Path
from typing import Any

from connector.exceptions import MoomooOrderError
from connector.orders import OrderSpec, OrderStatus, OrderType, OptionType, TradeSide
from datetime import date

from .safe_orders import SafeOrders


class ProposalExecutor:
    """Reads proposed trades written by the agent subprocess and executes them
    via SafeOrders. Returns a list of result dicts describing what happened."""

    def __init__(self, safe_orders: SafeOrders) -> None:
        self._safe_orders = safe_orders

    async def execute(self, proposals_path: Path) -> list[dict]:
        if not proposals_path.exists():
            return []
        results: list[dict] = []
        for line_no, line in enumerate(proposals_path.read_text().splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                proposal = json.loads(line)
            except json.JSONDecodeError as exc:
                results.append({
                    "line": line_no, "status": "parse_error", "error": str(exc),
                    "raw": line,
                })
                continue
            results.append(await self._execute_one(line_no, proposal))
        # consume: rename so a stale file isn't re-executed next tick
        proposals_path.unlink()
        return results

    async def _execute_one(self, line_no: int, proposal: dict) -> dict:
        action = proposal.get("action")
        try:
            if action == "place_order":
                spec = _parse_spec(proposal["spec"])
                order_id = await self._safe_orders.place_order(spec)
                return {"line": line_no, "status": "placed", "order_id": order_id,
                        "proposal": proposal}
            if action == "cancel_order":
                await self._safe_orders.cancel_order(proposal["order_id"])
                return {"line": line_no, "status": "cancelled",
                        "order_id": proposal["order_id"], "proposal": proposal}
            if action == "modify_order":
                await self._safe_orders.modify_order(
                    proposal["order_id"], qty=proposal["qty"], price=proposal["price"]
                )
                return {"line": line_no, "status": "modified",
                        "order_id": proposal["order_id"], "proposal": proposal}
            return {"line": line_no, "status": "unknown_action",
                    "action": action, "proposal": proposal}
        except MoomooOrderError as exc:
            return {"line": line_no, "status": "rejected",
                    "error": str(exc), "error_code": exc.error_code,
                    "proposal": proposal}
        except Exception as exc:
            return {"line": line_no, "status": "error",
                    "error": repr(exc), "proposal": proposal}


def _parse_spec(spec: dict) -> OrderSpec:
    expiry = spec.get("expiry")
    return OrderSpec(
        symbol=spec["symbol"],
        qty=int(spec["qty"]),
        side=TradeSide(spec["side"].lower()),
        order_type=OrderType(spec["order_type"].lower()),
        price=float(spec["price"]),
        expiry=date.fromisoformat(expiry) if expiry else None,
        strike=float(spec["strike"]) if spec.get("strike") is not None else None,
        option_type=OptionType(spec["option_type"].lower()) if spec.get("option_type") else None,
        contract_size=int(spec["contract_size"]) if spec.get("contract_size") is not None else None,
    )
