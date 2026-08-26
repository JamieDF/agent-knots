"""Tests for the SQLite project store."""

import pytest

from agent_knots.project.models import Project
from agent_knots.storage import project_store, reset_stores


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    reset_stores()
    yield project_store()
    reset_stores()


def test_create_get_list_update_delete(store):
    p = Project(id="ws1", name="Workspace One", description="Test")
    store.create(p)

    fetched = store.get("ws1")
    assert fetched is not None
    assert fetched.name == "Workspace One"

    listed = store.list()
    assert len(listed) == 1

    p.description = "Updated"
    store.update(p)
    assert store.get("ws1").description == "Updated"

    store.delete("ws1")
    assert store.get("ws1") is None


def test_create_duplicate_raises(store):
    store.create(Project(id="dup", name="One"))
    with pytest.raises(ValueError, match="already exists"):
        store.create(Project(id="dup", name="Two"))


def test_update_missing_raises(store):
    with pytest.raises(ValueError, match="not found"):
        store.update(Project(id="missing", name="Nope"))


def test_delete_missing_raises(store):
    with pytest.raises(ValueError, match="not found"):
        store.delete("missing")
