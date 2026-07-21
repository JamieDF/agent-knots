"""Tests for the board-stage and default-agent-role config stores."""

import tempfile
from pathlib import Path

import pytest

from agent_knots.workflows.models import DEFAULT_ROLES, DEFAULT_STAGES, Trigger
from agent_knots.workflows.store import RolesStore, StagesStore


@pytest.fixture
def stages_path():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "stages.yaml"


@pytest.fixture
def roles_path():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "roles.yaml"


class TestStagesStore:
    def test_list_returns_defaults_when_no_file(self, stages_path):
        store = StagesStore(stages_path)
        stages = store.list()
        assert [s.key for s in stages] == [s.key for s in DEFAULT_STAGES]
        assert not stages_path.exists()

    def test_abandoned_disabled_by_default(self, stages_path):
        store = StagesStore(stages_path)
        abandoned = next(s for s in store.list() if s.key == "abandoned")
        assert abandoned.enabled is False

    def test_toggle_persists(self, stages_path):
        store = StagesStore(stages_path)
        store.toggle("abandoned", True)
        assert stages_path.exists()
        abandoned = next(s for s in store.list() if s.key == "abandoned")
        assert abandoned.enabled is True

    def test_toggle_required_stage_off_raises(self, stages_path):
        store = StagesStore(stages_path)
        with pytest.raises(ValueError, match="required"):
            store.toggle("draft", False)

    def test_toggle_unknown_key_is_noop(self, stages_path):
        store = StagesStore(stages_path)
        stages = store.toggle("nonexistent", True)
        assert len(stages) == len(DEFAULT_STAGES)


class TestRolesStore:
    def test_list_returns_defaults_when_no_file(self, roles_path):
        store = RolesStore(roles_path)
        roles = store.list()
        assert [r.key for r in roles] == [r.key for r in DEFAULT_ROLES]

    def test_all_roles_disabled_by_default(self, roles_path):
        """Auto-firing a real agent session costs real API money — this
        must be opt-in, not something a fresh install silently does."""
        store = RolesStore(roles_path)
        assert all(not r.enabled for r in store.list())

    def test_get_unknown_role(self, roles_path):
        store = RolesStore(roles_path)
        assert store.get("nonexistent") is None

    def test_update_persists(self, roles_path):
        store = RolesStore(roles_path)
        updated = store.update("planner", enabled=True, model="gpt-4o")
        assert updated.enabled is True
        assert updated.model == "gpt-4o"
        reloaded = store.get("planner")
        assert reloaded.enabled is True
        assert reloaded.model == "gpt-4o"

    def test_update_unknown_role_raises(self, roles_path):
        store = RolesStore(roles_path)
        with pytest.raises(ValueError, match="not found"):
            store.update("nonexistent", enabled=True)

    def test_update_trigger(self, roles_path):
        store = RolesStore(roles_path)
        updated = store.update("builder", trigger="manual")
        assert updated.trigger == Trigger.MANUAL

    def test_enabled_for_trigger(self, roles_path):
        store = RolesStore(roles_path)
        assert store.enabled_for_trigger(Trigger.IS_STARTED) == []
        store.update("builder", enabled=True)
        matches = store.enabled_for_trigger(Trigger.IS_STARTED)
        assert len(matches) == 1
        assert matches[0].key == "builder"
