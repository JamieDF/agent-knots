"""YAML file-backed store for policy rules — single file, same pattern
as workflows/store.py's StagesStore/RolesStore."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from agent_knots.policies.models import DEFAULT_POLICIES, Policy


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
    """CRUD for the policy-rule config list, backed by one YAML file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def list(self) -> list[Policy]:
        if not self._path.exists():
            return copy.deepcopy(DEFAULT_POLICIES)
        try:
            data = yaml.safe_load(self._path.read_text())
            if not isinstance(data, list):
                return copy.deepcopy(DEFAULT_POLICIES)
            return [_policy_from_dict(d) for d in data]
        except (yaml.YAMLError, OSError, KeyError):
            return copy.deepcopy(DEFAULT_POLICIES)

    def save(self, policies: list[Policy]) -> None:
        data = [_policy_to_dict(p) for p in policies]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        tmp.rename(self._path)

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
