"""Tests for the policy-rules config store."""

import tempfile
from pathlib import Path

import pytest

from agent_knots.policies.models import DEFAULT_POLICIES
from agent_knots.policies.store import PolicyStore


@pytest.fixture
def policies_path():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "policies.yaml"


class TestPolicyStore:
    def test_list_returns_defaults_when_no_file(self, policies_path):
        store = PolicyStore(policies_path)
        policies = store.list()
        assert [p.key for p in policies] == [p.key for p in DEFAULT_POLICIES]
        assert not policies_path.exists()

    def test_all_policies_disabled_by_default(self, policies_path):
        store = PolicyStore(policies_path)
        assert all(not p.enabled for p in store.list())

    def test_only_spend_cap_is_enforced(self, policies_path):
        store = PolicyStore(policies_path)
        enforced = [p.key for p in store.list() if p.enforced]
        assert enforced == ["spend_cap"]

    def test_update_persists(self, policies_path):
        store = PolicyStore(policies_path)
        updated = store.update("spend_cap", enabled=True, value="5.00")
        assert updated.enabled is True
        assert updated.value == "5.00"
        assert policies_path.exists()

        reloaded = store.get("spend_cap")
        assert reloaded.enabled is True
        assert reloaded.value == "5.00"

    def test_update_unknown_policy_raises(self, policies_path):
        store = PolicyStore(policies_path)
        with pytest.raises(ValueError, match="not found"):
            store.update("nonexistent", enabled=True)

    def test_update_does_not_corrupt_shared_defaults(self, policies_path):
        """Regression guard for the same class of bug found in
        StagesStore/RolesStore: list() must not return objects that
        alias the module-level DEFAULT_POLICIES instances."""
        store = PolicyStore(policies_path)
        store.update("no_sudo", enabled=True)

        other_path = policies_path.with_name("other.yaml")
        other_store = PolicyStore(other_path)
        no_sudo = next(p for p in other_store.list() if p.key == "no_sudo")
        assert no_sudo.enabled is False
