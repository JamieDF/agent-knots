"""SQLite-backed store for policy rules — whole-document blob in
state.db, same pattern as workflows/store.py's StagesStore/RolesStore."""

from __future__ import annotations

import copy
from typing import Any

from agent_knots.policies.models import DEFAULT_POLICIES, Policy
from agent_knots.storage.blobs import KEY_POLICIES, get_blob, set_blob


def _policy_to_dict(p: Policy) -> dict[str, Any]:
    return {
        "key": p.key, "label": p.label, "description": p.description,
        "enabled": p.enabled, "value": p.value, "enforced": p.enforced,
    }


def _policy_from_dict(d: dict[str, Any]) -> Policy:
    return Policy(
        key=d["key"], label=d["label"], description=d.get("description", ""),
        enabled=d.get("enabled", False), value=d.get("value", ""),
        enforced=d.get("enforced", False),
    )


class PolicyStore:
    """CRUD for the policy-rule config list."""

    def list(self) -> list[Policy]:
        data = get_blob(KEY_POLICIES)
        if not isinstance(data, list):
            return copy.deepcopy(DEFAULT_POLICIES)
        try:
            return [_policy_from_dict(d) for d in data]
        except KeyError:
            return copy.deepcopy(DEFAULT_POLICIES)

    def save(self, policies: list[Policy]) -> None:
        set_blob(KEY_POLICIES, [_policy_to_dict(p) for p in policies])

    def get(self, key: str) -> Policy | None:
        return next((p for p in self.list() if p.key == key), None)

    def update(self, key: str, **changes: Any) -> Policy:
        policies = self.list()
        policy = next((p for p in policies if p.key == key), None)
        if policy is None:
            raise ValueError(f"policy {key!r} not found")
        for field_name, value in changes.items():
            if value is not None:
                setattr(policy, field_name, value)
        self.save(policies)
        return policy
