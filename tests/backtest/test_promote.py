import json
from pathlib import Path

import pytest

from backtest.promote import promote_learnings


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(e) for e in entries) + "\n"
    path.write_text(body)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


async def test_promote_appends_entries_to_live(tmp_path):
    live = tmp_path / "live"
    backtest_run = tmp_path / "live" / "backtests" / "run1"

    _write_jsonl(live / "learnings" / "learnings.jsonl", [
        {"id": "live-1", "active": True, "observation": "live entry",
         "category": "general", "evidence": "...", "created_at": "2026-05-01"},
    ])
    _write_jsonl(backtest_run / "learnings" / "learnings.jsonl", [
        {"id": "bt-1", "active": True, "observation": "bt entry",
         "category": "general", "evidence": "...", "created_at": "2026-05-04"},
    ])

    summary = await promote_learnings(run_id="run1", live_root=live)

    final = _read_jsonl(live / "learnings" / "learnings.jsonl")
    assert len(final) == 2
    bt_entry = next(e for e in final if "bt-" in e["id"])
    assert bt_entry["source"] == "backtest:run1"
    assert bt_entry["confidence"] == "low"


async def test_promote_handles_id_collision(tmp_path):
    live = tmp_path / "live"
    backtest_run = tmp_path / "live" / "backtests" / "run1"

    _write_jsonl(live / "learnings" / "learnings.jsonl", [
        {"id": "shared", "active": True, "observation": "live",
         "category": "general", "evidence": "...", "created_at": "2026-05-01"},
    ])
    _write_jsonl(backtest_run / "learnings" / "learnings.jsonl", [
        {"id": "shared", "active": True, "observation": "bt",
         "category": "general", "evidence": "...", "created_at": "2026-05-04"},
    ])

    await promote_learnings(run_id="run1", live_root=live)

    final = _read_jsonl(live / "learnings" / "learnings.jsonl")
    assert len(final) == 2
    bt_entry = next(e for e in final if e["observation"] == "bt")
    assert bt_entry["id"] == "shared_bt_run1"
    assert bt_entry["original_id"] == "shared"


async def test_promote_raises_when_run_directory_missing(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    with pytest.raises(FileNotFoundError):
        await promote_learnings(run_id="nonexistent", live_root=live)


async def test_promote_handles_empty_live_learnings(tmp_path):
    live = tmp_path / "live"
    backtest_run = tmp_path / "live" / "backtests" / "run1"
    _write_jsonl(backtest_run / "learnings" / "learnings.jsonl", [
        {"id": "bt-1", "active": True, "observation": "bt entry",
         "category": "general", "evidence": "...", "created_at": "2026-05-04"},
    ])
    await promote_learnings(run_id="run1", live_root=live)
    final = _read_jsonl(live / "learnings" / "learnings.jsonl")
    assert len(final) == 1
    assert final[0]["source"] == "backtest:run1"
