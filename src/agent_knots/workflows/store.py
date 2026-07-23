"""YAML file-backed stores for board-stage and default-agent-role config.

Single-file stores (not one-file-per-item like tasks/projects) since
both are small, fixed-cardinality lists edited as a whole on the
Workflows screen.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from agent_knots.workflows.models import DEFAULT_ROLES, DEFAULT_STAGES, Role, Stage, Trigger
from agent_knots.yamlfile import atomic_write_yaml, safe_read_yaml


def _stage_to_dict(s: Stage) -> dict[str, Any]:
    return {"key": s.key, "label": s.label, "statuses": s.statuses, "enabled": s.enabled, "required": s.required}


def _stage_from_dict(d: dict[str, Any]) -> Stage:
    return Stage(
        key=d["key"], label=d["label"], statuses=d.get("statuses", []),
        enabled=d.get("enabled", True), required=d.get("required", False),
    )


def _role_to_dict(r: Role) -> dict[str, Any]:
    return {
        "key": r.key, "name": r.name, "icon": r.icon, "description": r.description,
        "model": r.model, "trigger": r.trigger.value, "prompt": r.prompt,
        "tools": r.tools, "enabled": r.enabled,
    }


def _role_from_dict(d: dict[str, Any]) -> Role:
    return Role(
        key=d["key"], name=d["name"], icon=d.get("icon", ""), description=d.get("description", ""),
        model=d.get("model", ""), trigger=Trigger(d.get("trigger", "manual")),
        prompt=d.get("prompt", ""), tools=d.get("tools", []), enabled=d.get("enabled", False),
    )


class StagesStore:
    """CRUD for the board-stage config list, backed by one YAML file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def list(self) -> list[Stage]:
        if not self._path.exists():
            return copy.deepcopy(DEFAULT_STAGES)
        data = safe_read_yaml(self._path)
        if not isinstance(data, list):
            return copy.deepcopy(DEFAULT_STAGES)
        try:
            return [_stage_from_dict(d) for d in data]
        except KeyError:
            return copy.deepcopy(DEFAULT_STAGES)

    def save(self, stages: list[Stage]) -> None:
        atomic_write_yaml(self._path, [_stage_to_dict(s) for s in stages])

    def toggle(self, key: str, enabled: bool) -> list[Stage]:
        stages = self.list()
        for s in stages:
            if s.key == key:
                if s.required and not enabled:
                    raise ValueError(f"stage {key!r} is required and cannot be disabled")
                s.enabled = enabled
        self.save(stages)
        return stages


class RolesStore:
    """CRUD for the default-agent-role config list, backed by one YAML file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def list(self) -> list[Role]:
        if not self._path.exists():
            return copy.deepcopy(DEFAULT_ROLES)
        data = safe_read_yaml(self._path)
        if not isinstance(data, list):
            return copy.deepcopy(DEFAULT_ROLES)
        try:
            return [_role_from_dict(d) for d in data]
        except KeyError:
            return copy.deepcopy(DEFAULT_ROLES)

    def save(self, roles: list[Role]) -> None:
        atomic_write_yaml(self._path, [_role_to_dict(r) for r in roles])

    def get(self, key: str) -> Role | None:
        return next((r for r in self.list() if r.key == key), None)

    def update(self, key: str, **changes: Any) -> Role:
        roles = self.list()
        role = next((r for r in roles if r.key == key), None)
        if role is None:
            raise ValueError(f"role {key!r} not found")
        for field_name, value in changes.items():
            if field_name == "trigger" and value is not None:
                value = Trigger(value)
            if value is not None:
                setattr(role, field_name, value)
        self.save(roles)
        return role

    def enabled_for_trigger(self, trigger: Trigger) -> list[Role]:
        return [r for r in self.list() if r.enabled and r.trigger == trigger]
