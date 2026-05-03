# Order Status Subscription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time order status updates (broker rejections, cancellations, partial-fill progress) by subscribing to the moomoo SDK's order update stream, mirroring the existing `subscribe_fills` pattern.

**Architecture:** A new `Orders.subscribe_order_updates(callback)` method on the connector pushes order status events into a buffer that the engine drains each tick, writes to `recent_order_updates.json`, and surfaces to the agent via the existing prompt builder.

**Tech Stack:** Python 3.11+, moomoo-api (`ft.TradeOrderHandlerBase`), pytest, pytest-asyncio

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `connector/orders.py` | Modify | Add `subscribe_order_updates` and `_dispatch_order_updates` |
| `tests/connector/test_orders.py` | Modify | Add 2 tests for the new subscription |
| `data/store.py` | Modify | Add `recent_order_updates_path()` |
| `tests/data/test_store.py` | Modify | Add 1 test for the new path |
| `engine/loop.py` | Modify | Add `order_update_buffer` param, drain it each tick, write file, pass to prompt, restore on collector failure |
| `tests/engine/test_loop.py` | Modify | Update fixtures + add 2 tests (drain + collector-failure preservation) |
| `agent/prompt.py` | Modify | Add `recent_order_updates` param, include in state JSON, add file path, update system prompt |
| `tests/agent/test_prompt.py` | Modify | Update existing build calls + add 1 test for the new field |
| `main.py` | Modify | Wire `order_update_buffer` and the new subscription |

---

### Task 1: `Orders.subscribe_order_updates` on the connector

**Files:**
- Modify: `connector/orders.py`
- Modify: `tests/connector/test_orders.py`

- [ ] **Step 1: Add eager init for `_order_update_tasks` in `Orders.__init__`**

Open `connector/orders.py` and locate the `Orders.__init__` method. After the existing `self._fill_tasks: list[asyncio.Task] = []` line, append:

```python
        self._order_update_tasks: list[asyncio.Task] = []
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/connector/test_orders.py`:

```python
async def test_subscribe_order_updates_registers_handler(mock_conn):
    orders = Orders(mock_conn)
    received = []
    await orders.subscribe_order_updates(lambda update: received.append(update))

    # set_handler called twice if subscribe_fills was also tested? No — fixtures isolate.
    # Should be called exactly once with a TradeOrderHandlerBase subclass.
    mock_conn.trade_ctx.set_handler.assert_called_once()
    handler = mock_conn.trade_ctx.set_handler.call_args.args[0]
    import moomoo as ft
    assert isinstance(handler, ft.TradeOrderHandlerBase)


async def test_subscribe_order_updates_dispatches_to_callback(mock_conn):
    import asyncio
    import moomoo as ft
    from unittest.mock import patch

    orders = Orders(mock_conn)
    received: list[dict] = []
    done = asyncio.Event()

    def callback(update):
        received.append(update)
        done.set()

    await orders.subscribe_order_updates(callback)

    handler = mock_conn.trade_ctx.set_handler.call_args.args[0]
    update_df = pd.DataFrame([{
        "order_id": "ORD001",
        "code": "US.AAPL",
        "trd_side": "BUY",
        "qty": 10,
        "price": 150.0,
        "filled_qty": 0,
        "order_status": "SUBMITTED",
        "updated_time": "2024-01-15 10:00:01",
        "create_time": "2024-01-15 10:00:00",
    }])

    with patch.object(ft.TradeOrderHandlerBase, "on_recv_rsp", return_value=(ft.RET_OK, update_df)):
        handler.on_recv_rsp(object())

    await asyncio.wait_for(done.wait(), timeout=1.0)
    assert received[0]["order_id"] == "ORD001"
    assert received[0]["symbol"] == "US.AAPL"
    assert received[0]["side"] == "BUY"
    assert received[0]["qty"] == 10
    assert received[0]["price"] == 150.0
    assert received[0]["filled_qty"] == 0
    assert received[0]["order_status"] == "SUBMITTED"
    assert received[0]["updated_at"] == "2024-01-15 10:00:01"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/connector/test_orders.py::test_subscribe_order_updates_registers_handler tests/connector/test_orders.py::test_subscribe_order_updates_dispatches_to_callback -v`
Expected: FAIL with `AttributeError: 'Orders' object has no attribute 'subscribe_order_updates'`.

- [ ] **Step 4: Write the implementation**

In `connector/orders.py`, append to the `Orders` class (after `_dispatch_fills`):

```python
    async def subscribe_order_updates(self, callback: Callable[[dict], None]) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        class _OrderUpdateHandler(ft.TradeOrderHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code == ft.RET_OK and not content.empty:
                    for _, row in content.iterrows():
                        updated_at = row.get("updated_time") or row.get("create_time")
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "order_id": str(row["order_id"]),
                            "symbol": row["code"],
                            "side": row["trd_side"],
                            "qty": int(row["qty"]),
                            "price": float(row["price"]),
                            "filled_qty": int(row["filled_qty"]),
                            "order_status": row["order_status"],
                            "updated_at": updated_at,
                        })
                return ret_code, content

        self._conn.trade_ctx.set_handler(_OrderUpdateHandler())
        task = asyncio.create_task(self._dispatch_order_updates(queue, callback))
        self._order_update_tasks.append(task)

    @staticmethod
    async def _dispatch_order_updates(queue: asyncio.Queue, callback: Callable[[dict], None]) -> None:
        while True:
            data = await queue.get()
            try:
                callback(data)
            except Exception:
                pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/connector/test_orders.py -v`
Expected: 14 passed (12 prior + 2 new).

- [ ] **Step 6: Commit**

```bash
git add connector/orders.py tests/connector/test_orders.py
git commit -m "feat: add subscribe_order_updates to Orders module"
```

---

### Task 2: `DataStore.recent_order_updates_path`

**Files:**
- Modify: `data/store.py`
- Modify: `tests/data/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_store.py`:

```python
def test_recent_order_updates_path(tmp_path):
    store = DataStore(tmp_path)
    assert store.recent_order_updates_path() == (
        tmp_path / "account" / "recent_order_updates.json"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/data/test_store.py::test_recent_order_updates_path -v`
Expected: FAIL with `AttributeError: 'DataStore' object has no attribute 'recent_order_updates_path'`.

- [ ] **Step 3: Write the implementation**

In `data/store.py`, add a method to the `DataStore` class (place it next to `recent_fills_path`):

```python
    def recent_order_updates_path(self) -> Path:
        return self.root / "account" / "recent_order_updates.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/data/test_store.py -v`
Expected: all DataStore tests pass (previous count + 1).

- [ ] **Step 5: Commit**

```bash
git add data/store.py tests/data/test_store.py
git commit -m "feat: add recent_order_updates_path to DataStore"
```

---

### Task 3: Engine drains and persists order updates

**Files:**
- Modify: `engine/loop.py`
- Modify: `tests/engine/test_loop.py`

- [ ] **Step 1: Update test fixtures**

In `tests/engine/test_loop.py`, locate the `deps` fixture and add an `order_update_buffer` to its return tuple. The existing fixture returns `(collector, runner, prompt_builder, account, orders, fill_buffer, executor, store)` (or similar — match the actual current shape). Add `order_update_buffer: list[dict] = []` and include it in the returned tuple.

The new fixture body:

```python
@pytest.fixture
def deps():
    collector = MagicMock()
    collector.collect = AsyncMock()
    runner = MagicMock()
    runner.run = AsyncMock(return_value=AgentResult(
        exit_code=0, stdout="ok", stderr="", duration_seconds=0.1, timed_out=False,
    ))
    prompt_builder = MagicMock()
    prompt_builder.build = MagicMock(return_value="prompt")
    account = MagicMock()
    account.get_balance = AsyncMock(return_value={
        "cash": 10000.0, "buying_power": 20000.0,
        "total_assets": 100000.0, "market_value": 90000.0, "currency": "USD",
    })
    account.get_positions = AsyncMock(return_value=[])
    orders = MagicMock()
    orders.get_orders = AsyncMock(return_value=[])
    fill_buffer: list[dict] = []
    order_update_buffer: list[dict] = []
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=[])
    store = MagicMock()
    store.proposed_trades_path = MagicMock(return_value=Path("/tmp/proposals.jsonl"))
    store.proposal_results_path = MagicMock(return_value=Path("/tmp/results.json"))
    store.recent_fills_path = MagicMock(return_value=Path("/tmp/recent_fills.json"))
    store.recent_order_updates_path = MagicMock(return_value=Path("/tmp/recent_order_updates.json"))
    store.atomic_write_text = MagicMock()
    return (collector, runner, prompt_builder, account, orders,
            fill_buffer, order_update_buffer, executor, store)
```

Then update every test that unpacks `deps` to include `order_update_buffer` and pass it into `Engine(...)` constructor calls. Find every line like:

```python
collector, runner, prompt_builder, account, orders, fill_buffer, executor, store = deps
```

and replace with:

```python
collector, runner, prompt_builder, account, orders, fill_buffer, order_update_buffer, executor, store = deps
```

Find every `Engine(` constructor call and add `order_update_buffer=order_update_buffer,` as a kwarg (place it next to `fill_buffer=fill_buffer,`).

- [ ] **Step 2: Add the failing test for drain + write**

Append to `tests/engine/test_loop.py`:

```python
async def test_tick_drains_order_update_buffer(deps):
    (collector, runner, prompt_builder, account, orders,
     fill_buffer, order_update_buffer, executor, store) = deps
    order_update_buffer.append({
        "order_id": "ORD001", "symbol": "US.AAPL", "side": "BUY",
        "qty": 10, "price": 150.0, "filled_qty": 0,
        "order_status": "SUBMITTED", "updated_at": "2024-01-16 10:00:01",
    })
    config = _make_config()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=store, log_writer=MagicMock(),
    )
    engine.set_baseline_total_assets(100000.0)
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)

    # buffer drained
    assert order_update_buffer == []
    # prompt_builder received the update
    args, kwargs = prompt_builder.build.call_args
    assert kwargs["recent_order_updates"][0]["order_id"] == "ORD001"
    # file written via atomic_write_text — check the call list for our path
    write_paths = [call.args[0] for call in store.atomic_write_text.call_args_list]
    assert Path("/tmp/recent_order_updates.json") in write_paths


async def test_collector_failure_preserves_order_updates(deps):
    (collector, runner, prompt_builder, account, orders,
     fill_buffer, order_update_buffer, executor, store) = deps
    order_update_buffer.append({
        "order_id": "ORD001", "symbol": "US.AAPL", "side": "BUY",
        "qty": 10, "price": 150.0, "filled_qty": 0,
        "order_status": "SUBMITTED", "updated_at": "2024-01-16 10:00:01",
    })
    collector.collect = AsyncMock(side_effect=RuntimeError("network down"))
    config = _make_config()
    log_writer = MagicMock()
    engine = Engine(
        config=config, collector=collector, runner=runner,
        prompt_builder=prompt_builder, account=account, orders=orders,
        fill_buffer=fill_buffer, order_update_buffer=order_update_buffer,
        executor=executor, store=store, log_writer=log_writer,
    )
    open_time = datetime(2024, 1, 16, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    await engine.tick(now=open_time)

    # update should be back in the buffer
    assert len(order_update_buffer) == 1
    assert order_update_buffer[0]["order_id"] == "ORD001"
    runner.run.assert_not_awaited()
```

- [ ] **Step 3: Run new tests to verify they fail**

Run: `pytest tests/engine/test_loop.py::test_tick_drains_order_update_buffer tests/engine/test_loop.py::test_collector_failure_preserves_order_updates -v`
Expected: FAIL — `Engine.__init__` does not accept `order_update_buffer`.

- [ ] **Step 4: Update Engine constructor and tick**

In `engine/loop.py`:

Add `order_update_buffer: list[dict]` to the `Engine.__init__` signature, next to `fill_buffer`. Store it: `self._order_update_buffer = order_update_buffer`.

In `tick()`, find the existing fill drain block:

```python
        recent_fills = list(self._fill_buffer)
        self._fill_buffer.clear()
```

Add immediately after it:

```python
        recent_order_updates = list(self._order_update_buffer)
        self._order_update_buffer.clear()
```

In the collector-failure handler, find the existing fill restore line:

```python
            self._fill_buffer[:0] = recent_fills  # restore fills for next tick
```

Add immediately after:

```python
            self._order_update_buffer[:0] = recent_order_updates  # restore updates
```

In the circuit-breaker-trip block (where `_fill_buffer[:0] = recent_fills` is called), add:

```python
            self._order_update_buffer[:0] = recent_order_updates
```

After the existing `recent_fills.json` write (`self._store.atomic_write_text(self._store.recent_fills_path(), ...)`), add:

```python
        self._store.atomic_write_text(
            self._store.recent_order_updates_path(),
            json.dumps(recent_order_updates, indent=2, default=str),
        )
```

In the `prompt_builder.build(...)` call, add `recent_order_updates=recent_order_updates,` to the kwargs.

- [ ] **Step 5: Run all engine tests to verify**

Run: `pytest tests/engine/test_loop.py -v`
Expected: all tests pass (previous count + 2 new).

- [ ] **Step 6: Commit**

```bash
git add engine/loop.py tests/engine/test_loop.py
git commit -m "feat: Engine drains and persists order_update_buffer each tick"
```

---

### Task 4: PromptBuilder includes order updates

**Files:**
- Modify: `agent/prompt.py`
- Modify: `tests/agent/test_prompt.py`

- [ ] **Step 1: Update existing test fixtures + write the new test**

In `tests/agent/test_prompt.py`, every existing call to `builder.build(...)` needs a new `recent_order_updates=[]` kwarg added (since the parameter will become required). Update each one — typically there are 4 existing test functions that call `builder.build`.

Append a new test:

```python
def test_prompt_includes_recent_order_updates(tmp_path):
    store = DataStore(tmp_path)
    builder = PromptBuilder(store=store, watchlist=["AAPL"], history_interval="1m")
    prompt = builder.build(
        now=datetime(2024, 1, 16, 10, 30),
        balance={"cash": 0.0, "buying_power": 0.0,
                 "total_assets": 0.0, "market_value": 0.0, "currency": "USD"},
        positions=[], open_orders=[],
        recent_fills=[],
        recent_order_updates=[{
            "order_id": "ORD001", "symbol": "US.AAPL", "side": "BUY",
            "qty": 10, "price": 150.0, "filled_qty": 0,
            "order_status": "FAILED", "updated_at": "2024-01-16 10:00:01",
        }],
        daily_pnl=0.0,
    )
    assert "ORD001" in prompt
    assert "FAILED" in prompt
    assert str(store.recent_order_updates_path()) in prompt
```

- [ ] **Step 2: Run new test to verify it fails**

Run: `pytest tests/agent/test_prompt.py::test_prompt_includes_recent_order_updates -v`
Expected: FAIL — `build()` does not accept `recent_order_updates` parameter.

- [ ] **Step 3: Update PromptBuilder.build**

In `agent/prompt.py`:

Add `recent_order_updates: list[dict]` as a required parameter to `build()`, placed right after `recent_fills: list[dict]`.

In the `state` dict construction, add the new field after `recent_fills_since_last_tick`:

```python
            "recent_order_updates_since_last_tick": recent_order_updates,
```

In the `files` dict construction (after the existing `"recent_fills"` entry), add:

```python
            "recent_order_updates": str(self._store.recent_order_updates_path()),
```

Update `_SYSTEM_PROMPT` — find the bullet list at the bottom of the docstring (after the trade proposal schema) and add a new bullet noting that broker-side order status changes (rejections, cancellations, transitions) appear in `recent_order_updates_since_last_tick` and the corresponding file in real time. The exact line to add (place it after the existing line about `recent_proposal_results`):

```
- Broker-side order status changes (rejections, cancellations, partial-fill progress)
  appear in `recent_order_updates_since_last_tick` and the recent_order_updates file
  in real time, as the broker reports them.
```

- [ ] **Step 4: Run all prompt tests to verify**

Run: `pytest tests/agent/test_prompt.py -v`
Expected: all 5 tests pass (4 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add agent/prompt.py tests/agent/test_prompt.py
git commit -m "feat: PromptBuilder surfaces recent_order_updates to the agent"
```

---

### Task 5: Wire it up in main.py + final integration check

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Wire the new buffer and subscription**

In `main.py`, locate the existing `fill_buffer` setup:

```python
        fill_buffer: list[dict] = []
        await orders.subscribe_fills(lambda fill: fill_buffer.append(fill))
```

Add immediately after:

```python
        order_update_buffer: list[dict] = []
        await orders.subscribe_order_updates(lambda update: order_update_buffer.append(update))
```

In the `Engine(...)` constructor call, add `order_update_buffer=order_update_buffer,` as a kwarg next to `fill_buffer=fill_buffer,`.

- [ ] **Step 2: Verify imports resolve**

Run:
```bash
python3 -c "
from engine.config import load_config
from engine.market_hours import is_market_open
from engine.safe_orders import SafeOrders
from engine.executor import ProposalExecutor
from engine.loop import Engine
from data.store import DataStore
from data.collector import Collector
from agent.runner import AgentRunner
from agent.prompt import PromptBuilder
from connector.orders import Orders
print('All imports OK')
"
```
Expected: `All imports OK`.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: all tests pass (previous 112 + 6 new = 118), no warnings.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "chore: wire order_update_buffer through main"
```
