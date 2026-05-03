import json

from data.store import DataStore


class LearningsStore:
    def __init__(self, store: DataStore) -> None:
        self._store = store

    def read_all(self) -> list[dict]:
        path = self._store.learnings_path()
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def read_active(self) -> list[dict]:
        return [e for e in self.read_all() if e.get("active") is True]

    def write(self, entries: list[dict]) -> None:
        if not entries:
            self._store.atomic_write_text(self._store.learnings_path(), "")
            return
        body = "\n".join(json.dumps(e, default=str) for e in entries) + "\n"
        self._store.atomic_write_text(self._store.learnings_path(), body)
