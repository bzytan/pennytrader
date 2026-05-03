import json
from pathlib import Path


async def promote_learnings(run_id: str, live_root: Path) -> dict:
    live_root = Path(live_root)
    backtest_path = live_root / "backtests" / run_id / "learnings" / "learnings.jsonl"
    if not backtest_path.exists():
        raise FileNotFoundError(f"backtest learnings not found: {backtest_path}")

    live_path = live_root / "learnings" / "learnings.jsonl"
    live_path.parent.mkdir(parents=True, exist_ok=True)

    live_entries = _read_jsonl(live_path)
    bt_entries = _read_jsonl(backtest_path)
    live_ids = {e["id"] for e in live_entries}

    imported = 0
    for entry in bt_entries:
        new_entry = dict(entry)
        new_entry["source"] = f"backtest:{run_id}"
        if "confidence" not in new_entry:
            new_entry["confidence"] = "low"
        if new_entry["id"] in live_ids:
            new_entry["original_id"] = new_entry["id"]
            new_entry["id"] = f"{new_entry['id']}_bt_{run_id}"
        live_entries.append(new_entry)
        live_ids.add(new_entry["id"])
        imported += 1

    body = "\n".join(json.dumps(e, default=str) for e in live_entries) + "\n"
    live_path.write_text(body)

    return {"imported": imported, "live_total": len(live_entries)}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
