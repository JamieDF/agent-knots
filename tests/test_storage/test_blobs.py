"""Tests for config blob get/set."""

import pytest

from agent_knots.storage import reset_stores
from agent_knots.storage.blobs import get_blob, set_blob


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    reset_stores()
    yield
    reset_stores()


def test_get_missing_returns_none():
    assert get_blob("settings") is None


def test_set_and_get_round_trip():
    set_blob("settings", {"finish_action": "merge"})
    assert get_blob("settings") == {"finish_action": "merge"}


def test_set_replaces_existing():
    set_blob("stages", [{"key": "a"}])
    set_blob("stages", [{"key": "b"}])
    assert get_blob("stages") == [{"key": "b"}]
