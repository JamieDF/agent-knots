"""Tests for the policy-rules config store."""

import pytest

from agent_knots.policies.models import DEFAULT_POLICIES
from agent_knots.policies.store import PolicyStore
from agent_knots.storage import reset_stores


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    reset_stores()
    yield
    reset_stores()


class TestPolicyStore:
    def test_list_returns_defaults_when_unset(self):
        store = PolicyStore()
        policies = store.list()
        assert [p.key for p in policies] == [p.key for p in DEFAULT_POLICIES]

    def test_all_policies_disabled_by_default(self):
        store = PolicyStore()
        assert all(not p.enabled for p in store.list())

    def test_only_spend_cap_is_enforced(self):
        store = PolicyStore()
        enforced = [p.key for p in store.list() if p.enforced]
        assert enforced == ["spend_cap"]

    def test_update_persists(self):
        store = PolicyStore()
        updated = store.update("spend_cap", enabled=True, value="5.00")
        assert updated.enabled is True
        assert updated.value == "5.00"

        reloaded = store.get("spend_cap")
        assert reloaded.enabled is True
        assert reloaded.value == "5.00"

    def test_update_unknown_policy_raises(self):
        store = PolicyStore()
        with pytest.raises(ValueError, match="not found"):
            store.update("nonexistent", enabled=True)

    def test_update_does_not_corrupt_shared_defaults(self):
        """list() must not return objects that alias the module-level
        DEFAULT_POLICIES instances."""
        store = PolicyStore()
        store.update("no_sudo", enabled=True)

        no_sudo_default = next(p for p in DEFAULT_POLICIES if p.key == "no_sudo")
        assert no_sudo_default.enabled is False
