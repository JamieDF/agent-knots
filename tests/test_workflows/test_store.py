"""Tests for the board-stage and default-agent-role config stores."""

import pytest

from agent_knots.storage import reset_stores
from agent_knots.workflows.models import DEFAULT_ROLES, DEFAULT_STAGES, Trigger
from agent_knots.workflows.store import RolesStore, StagesStore


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    reset_stores()
    yield
    reset_stores()


class TestStagesStore:
    def test_list_returns_defaults_when_unset(self):
        store = StagesStore()
        stages = store.list()
        assert [s.key for s in stages] == [s.key for s in DEFAULT_STAGES]

    def test_abandoned_disabled_by_default(self):
        store = StagesStore()
        abandoned = next(s for s in store.list() if s.key == "abandoned")
        assert abandoned.enabled is False

    def test_toggle_persists(self):
        store = StagesStore()
        store.toggle("abandoned", True)
        abandoned = next(s for s in store.list() if s.key == "abandoned")
        assert abandoned.enabled is True

    def test_toggle_required_stage_off_raises(self):
        store = StagesStore()
        with pytest.raises(ValueError, match="required"):
            store.toggle("draft", False)

    def test_toggle_unknown_key_is_noop(self):
        store = StagesStore()
        stages = store.toggle("nonexistent", True)
        assert len(stages) == len(DEFAULT_STAGES)


class TestRolesStore:
    def test_list_returns_defaults_when_unset(self):
        store = RolesStore()
        roles = store.list()
        assert [r.key for r in roles] == [r.key for r in DEFAULT_ROLES]

    def test_all_roles_disabled_by_default(self):
        """Auto-firing a real agent session costs real API money — this
        must be opt-in, not something a fresh install silently does."""
        store = RolesStore()
        assert all(not r.enabled for r in store.list())

    def test_get_unknown_role(self):
        store = RolesStore()
        assert store.get("nonexistent") is None

    def test_update_persists(self):
        store = RolesStore()
        updated = store.update("planner", enabled=True, model="gpt-4o")
        assert updated.enabled is True
        assert updated.model == "gpt-4o"
        reloaded = store.get("planner")
        assert reloaded.enabled is True
        assert reloaded.model == "gpt-4o"

    def test_update_unknown_role_raises(self):
        store = RolesStore()
        with pytest.raises(ValueError, match="not found"):
            store.update("nonexistent", enabled=True)

    def test_update_trigger(self):
        store = RolesStore()
        updated = store.update("builder", trigger="manual")
        assert updated.trigger == Trigger.MANUAL

    def test_enabled_for_trigger(self):
        store = RolesStore()
        assert store.enabled_for_trigger(Trigger.IS_STARTED) == []
        store.update("builder", enabled=True)
        matches = store.enabled_for_trigger(Trigger.IS_STARTED)
        assert len(matches) == 1
        assert matches[0].key == "builder"

    def test_reviewer_is_advisory_by_default(self):
        store = RolesStore()
        reviewer = store.get("reviewer")
        assert reviewer.advisory is True

    def test_builder_is_not_advisory_by_default(self):
        store = RolesStore()
        builder = store.get("builder")
        assert builder.advisory is False

    def test_advisory_round_trips_through_save(self):
        """advisory is a real persisted field, not decorative like tools
        used to be — a save/reload cycle must not silently drop it."""
        store = RolesStore()
        roles = store.list()
        for r in roles:
            if r.key == "planner":
                r.advisory = True
        store.save(roles)

        reloaded = RolesStore()
        planner = reloaded.get("planner")
        assert planner.advisory is True
        reviewer = reloaded.get("reviewer")
        assert reviewer.advisory is True
