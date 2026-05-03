import json
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from connector.account import Account
from connector.orders import Orders

from agent.runner import AgentResult, AgentRunner
from analytics.ledger import Ledger
from data.store import DataStore


_REQUIRED_LEARNING_FIELDS = {
    "id", "created_at", "category", "observation", "evidence", "active",
}


_DREAM_PROMPT = """You are reflecting on the autonomous trading agent's recent
activity. Your role is REFLECTIVE ANALYST, not trader. You will not place trades.

Your goal: identify patterns in the past data and update the agent's persistent
learnings file with new observations or refinements.

REQUIRED DISCIPLINE:
- Sample size: every observation must cite the trade count it's based on.
  Do not propose strategy changes based on fewer than 20 trades unless the
  pattern is overwhelming (e.g., 5 of 5).
- Provenance: every entry must include `evidence` (numbers, not vibes).
- Supersession: when refining or retiring an existing learning, mark the old
  entry `active: false` and add a new entry with `supersedes: <old_id>` rather
  than silently editing.

Inputs you may read:
- {trades_path} — closed trades (one JSON object per line)
- {equity_path} — daily account snapshots
- {performance_path} — pre-computed metrics
- {learnings_path} — current persistent learnings (JSONL)
- {decisions_dir}/decisions-YYYY-MM-DD.jsonl — past decision logs

You have full Claude Code tool access: read files, write Python scripts to
analyze them, run them, and observe results.

Outputs you must produce:
1. Write a markdown reflection to {dream_path} summarizing what you observed
   and what you decided to change. At least 200 characters.
2. Write the updated learnings to {learnings_path} as JSONL. Each entry must
   include the fields: id, created_at, category, observation, evidence, active.
   Optional fields: dream_id, confidence, supersedes.

Begin reflecting now. When done, exit cleanly."""


class DreamRunner:
    def __init__(
        self,
        ledger: Ledger,
        performance_fn: Callable[..., Awaitable[dict]],
        runner: AgentRunner,
        store: DataStore,
        log_writer,
        account: Account,
        orders: Orders,
    ) -> None:
        self._ledger = ledger
        self._performance_fn = performance_fn
        self._runner = runner
        self._store = store
        self._log_writer = log_writer
        self._account = account
        self._orders = orders

    async def run(self, now: datetime) -> bool:
        today = now.date()
        try:
            await self._ledger.rebuild(orders=self._orders, account=self._account, today=today)
            await self._performance_fn(store=self._store, account=self._account, today=today)
        except Exception as exc:
            self._log_writer.write({
                "event": "dream_failed",
                "time": now.isoformat(),
                "phase": "data_refresh",
                "error": repr(exc),
            })
            return False

        prior_learnings = self._snapshot_learnings()

        prompt = self._build_prompt(today)
        result: AgentResult = await self._runner.run(prompt)

        if result.exit_code != 0 or result.timed_out:
            self._log_writer.write({
                "event": "dream_failed",
                "time": now.isoformat(),
                "phase": "subprocess",
                "exit_code": result.exit_code,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
            })
            return False

        if not self._validate_outputs(prior_learnings, today):
            if prior_learnings is not None:
                self._store.atomic_write_text(self._store.learnings_path(), prior_learnings)
            self._log_writer.write({
                "event": "dream_validation_failed",
                "time": now.isoformat(),
            })
            return False

        self._store.atomic_write_text(self._store.last_dream_path(), today.isoformat() + "\n")
        self._log_writer.write({
            "event": "dream_completed",
            "time": now.isoformat(),
            "duration_seconds": result.duration_seconds,
        })
        return True

    def _snapshot_learnings(self) -> str | None:
        path = self._store.learnings_path()
        if not path.exists():
            return None
        return path.read_text()

    def _build_prompt(self, today) -> str:
        return _DREAM_PROMPT.format(
            trades_path=self._store.trades_path(),
            equity_path=self._store.equity_curve_path(),
            performance_path=self._store.performance_path(),
            learnings_path=self._store.learnings_path(),
            decisions_dir=self._store.root / "log",
            dream_path=self._store.dream_path(today),
        )

    def _validate_outputs(self, prior_learnings: str | None, today) -> bool:
        learnings_path = self._store.learnings_path()
        if not learnings_path.exists():
            return False
        try:
            new_entries = [
                json.loads(line) for line in learnings_path.read_text().splitlines()
                if line.strip()
            ]
        except json.JSONDecodeError:
            return False

        for entry in new_entries:
            if not _REQUIRED_LEARNING_FIELDS.issubset(entry.keys()):
                return False

        if prior_learnings:
            prior_count = len([
                line for line in prior_learnings.splitlines() if line.strip()
            ])
            if prior_count > 0 and len(new_entries) < prior_count * 0.5:
                return False

        dream_path = self._store.dream_path(today)
        if dream_path.exists() and len(dream_path.read_text()) < 200:
            self._log_writer.write({
                "event": "dream_markdown_short",
                "time": today.isoformat(),
                "size": len(dream_path.read_text()),
            })

        return True
