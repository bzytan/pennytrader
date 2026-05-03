import json

import pytest

from analytics.learnings import LearningsStore
from data.store import DataStore


@pytest.fixture
def store(tmp_path):
    s = DataStore(tmp_path)
    s.ensure_dirs()
    return s


def test_read_active_returns_empty_when_no_file(store):
    ls = LearningsStore(store=store)
    assert ls.read_active() == []


def test_read_active_filters_inactive_entries(store):
    body = "\n".join(json.dumps(e) for e in [
        {"id": "1", "active": True, "observation": "a"},
        {"id": "2", "active": False, "observation": "b"},
        {"id": "3", "active": True, "observation": "c"},
    ]) + "\n"
    store.atomic_write_text(store.learnings_path(), body)
    ls = LearningsStore(store=store)
    actives = ls.read_active()
    assert [e["id"] for e in actives] == ["1", "3"]


def test_write_replaces_full_file(store):
    body = json.dumps({"id": "old", "active": True, "observation": "old"}) + "\n"
    store.atomic_write_text(store.learnings_path(), body)
    ls = LearningsStore(store=store)
    ls.write([
        {"id": "new1", "active": True, "observation": "x"},
        {"id": "new2", "active": False, "observation": "y"},
    ])
    lines = store.learnings_path().read_text().splitlines()
    ids = [json.loads(l)["id"] for l in lines]
    assert ids == ["new1", "new2"]


def test_write_empty_list_produces_empty_file(store):
    ls = LearningsStore(store=store)
    ls.write([])
    assert store.learnings_path().read_text() == ""


def test_read_all_returns_all_entries_including_inactive(store):
    body = "\n".join(json.dumps(e) for e in [
        {"id": "1", "active": True, "observation": "a"},
        {"id": "2", "active": False, "observation": "b"},
    ]) + "\n"
    store.atomic_write_text(store.learnings_path(), body)
    ls = LearningsStore(store=store)
    assert len(ls.read_all()) == 2
