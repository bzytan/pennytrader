# Order Status Subscription Design

## Overview

Add real-time visibility into order status transitions (broker rejections, cancellations, partial-fill progress, etc.) by subscribing to the moomoo SDK's order update stream. Today the agent only learns about non-fill order outcomes by polling `get_orders()` once per heartbeat — fine for a 60-second heartbeat, but blind on longer cadences. This change closes the gap by mirroring the existing fill-subscription pattern.

## Goals

- Capture every order status event the SDK emits (no filtering at the connector layer)
- Surface those events to the autonomous agent each tick the same way fills are surfaced
- Reuse the established subscription pattern (`subscribe_quotes`, `subscribe_fills`) for consistency

## Non-Goals

- Re-registering subscriptions after a connection drop. This is a known gap that affects all three subscription types equally and will be addressed as a separate connector improvement.
- Filtering or interpreting status values at the connector layer. The agent decides what matters.

## Architecture

The change is a thin pass-through addition that follows the established pattern:

```
moomoo SDK → ft.TradeOrderHandlerBase → asyncio.Queue → background task → callback
                                                                              │
                                                                              ▼
                                                                  order_update_buffer (list)
                                                                              │
                                                              drained by Engine.tick()
                                                                              │
                                                                              ▼
                                                       .trading_data/account/recent_order_updates.json
                                                                              │
                                                                              ▼
                                                              prompt → agent reads
```

No new modules. Each existing module gets a small addition.

## Component Changes

### `connector/orders.py`

Add a new method `Orders.subscribe_order_updates(callback)` that mirrors `Orders.subscribe_fills` exactly, except it uses `ft.TradeOrderHandlerBase` instead of `ft.TradeDealHandlerBase`. The dispatch loop pushes a normalized dict per row:

```python
{
    "order_id": str,
    "symbol": str,           # from "code"
    "side": str,             # from "trd_side"
    "qty": int,
    "price": float,
    "filled_qty": int,
    "order_status": str,     # e.g., "SUBMITTED", "CANCELLED_ALL", "FAILED"
    "updated_at": str,       # from "updated_time", falling back to "create_time"
}
```

Add `self._order_update_tasks: list[asyncio.Task] = []` to `Orders.__init__`, parallel to `_fill_tasks`. The dispatch loop uses the same try/except suppression pattern as fills.

### `data/store.py`

Add one path helper:

```python
def recent_order_updates_path(self) -> Path:
    return self.root / "account" / "recent_order_updates.json"
```

### `engine/loop.py`

Extend the `Engine` constructor with a new parameter `order_update_buffer: list[dict]`. In `tick()`, after the existing fill-buffer drain (which happens early so fills are preserved on collector failure), add an analogous order-update drain:

```python
recent_order_updates = list(self._order_update_buffer)
self._order_update_buffer.clear()
```

After the collector succeeds, write the snapshot to disk via the existing atomic-write pattern, alongside the recent_fills write:

```python
self._store.atomic_write_text(
    self._store.recent_order_updates_path(),
    json.dumps(recent_order_updates, indent=2, default=str),
)
```

Pass `recent_order_updates=recent_order_updates` into the prompt builder call.

If the collector raises, restore the order-update buffer the same way fills are restored: `self._order_update_buffer[:0] = recent_order_updates`.

### `agent/prompt.py`

Extend `PromptBuilder.build()` with a new parameter `recent_order_updates: list[dict]`. Include it in the inline state JSON alongside `recent_fills_since_last_tick`:

```python
state = {
    ...,
    "recent_fills_since_last_tick": recent_fills,
    "recent_order_updates_since_last_tick": recent_order_updates,
    ...,
}
```

Add the file path to the `files` dict:

```python
files["recent_order_updates"] = str(self._store.recent_order_updates_path())
```

Update `_SYSTEM_PROMPT` with a one-line note: that broker-side rejections, cancellations, and other order state transitions surface in `recent_order_updates_since_last_tick` (and the corresponding file) in real time.

### `main.py`

Wire a new buffer alongside the existing `fill_buffer`:

```python
order_update_buffer: list[dict] = []
await orders.subscribe_order_updates(lambda update: order_update_buffer.append(update))
```

Pass `order_update_buffer=order_update_buffer` into the `Engine` constructor call.

## Testing

All new tests follow established patterns. Mock the SDK at the boundary; no live OpenD required.

- **`tests/connector/test_orders.py`** — 2 new tests:
  - `test_subscribe_order_updates_registers_handler` — verifies `set_handler` is called with a `TradeOrderHandlerBase` subclass
  - `test_subscribe_order_updates_dispatches_to_callback` — verifies a status event flows from the handler through the queue to the user callback, with all expected fields populated
- **`tests/data/test_store.py`** — 1 new test for `recent_order_updates_path`
- **`tests/engine/test_loop.py`** — 1 new test `test_tick_drains_order_update_buffer` (parallel to the existing fill-buffer test) that verifies:
  - The order-update buffer is drained
  - `recent_order_updates.json` is written via `atomic_write_text`
  - `prompt_builder.build()` receives the updates in `recent_order_updates`
  - Existing fill-buffer test stays green (no regressions)
- **`tests/engine/test_loop.py`** — 1 new test `test_collector_failure_preserves_order_updates` mirroring `test_collector_failure_preserves_fills_for_next_tick`
- **`tests/agent/test_prompt.py`** — 1 new test `test_prompt_includes_recent_order_updates` verifying the state field and the file path both appear in the rendered prompt

## Error Handling

| Failure | Handling |
|---|---|
| SDK callback raises | Suppressed in `_dispatch_order_updates` (same as fills/quotes) |
| Collector failure mid-tick | Buffer restored via `[:0]` insertion (same as fills) |
| Connection drop and reconnect | Subscription is lost. Out of scope for this change. |
| Buffer growing unboundedly between ticks | Acceptable: order updates are low-frequency. If it becomes a problem, add a max-size cap. |

## Out of Scope

- Subscription re-registration after reconnect (cross-cutting concern affecting all subscriptions)
- Holiday calendar (separate spec)
- Performance analytics (separate spec)
