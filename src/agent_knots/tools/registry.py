"""Tool registry — manages available tools (built-in + custom).

Custom tools are user-defined shell commands persisted to YAML.
They get wrapped as Strands tools at session creation time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_knots.config import settings_file as _settings_path
from agent_knots.tools.defaults import DEFAULT_TOOLS, auto_approve_tools

# ── tool info ────────────────────────────────────────────────────────────────


@dataclass
class ToolInfo:
    """Metadata about a tool, for display in the UI."""
    name: str
    description: str = ""
    builtin: bool = True      # built-in vs custom
    enabled: bool = True       # user can disable tools
    created_at: float = 0.0

    @property
    def id(self) -> str:
        return self.name


# ── custom tool ──────────────────────────────────────────────────────────────


@dataclass
class CustomTool:
    """A user-defined tool that wraps a shell command.

    Example:
        CustomTool(
            name="run_tests",
            description="Run the project test suite",
            command="pytest {path} -v",
            parameters=[{"name": "path", "type": "string", "description": "Test directory"}],
        )
    """
    name: str
    description: str = ""
    command: str = ""             # shell command with {param} placeholders
    parameters: list[dict[str, str]] = field(default_factory=list)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    def to_strands_tool(self, cwd: str | None = None):
        """Convert to a Strands DecoratedFunctionTool.

        Args:
            cwd: Workspace directory to run the command in. Without this,
                the command runs in the server process's own working
                directory, which ignores any session workspace entirely.
        """
        from strands.tools import tool as _tool_dec

        from agent_knots.sandbox_tools import run_confined

        cmd = self.command
        params = self.parameters
        desc = self.description

        # Build a function that executes the command.
        def _custom_tool(**kwargs: Any) -> dict:
            # Substitute parameters into the command.
            resolved = cmd
            for p in params:
                key = p["name"]
                val = kwargs.get(key, "")
                resolved = resolved.replace("{" + key + "}", str(val))

            return run_confined(resolved, cwd=cwd)

        _custom_tool.__name__ = self.name
        _custom_tool.__doc__ = desc
        return _tool_dec(_custom_tool, description=desc)

    def to_info(self) -> ToolInfo:
        return ToolInfo(
            name=self.name,
            description=self.description,
            builtin=False,
            enabled=self.enabled,
            created_at=self.created_at,
        )


# ── registry ─────────────────────────────────────────────────────────────────


class ToolRegistry:
    """Manages available tools: built-in + custom (YAML-persisted)."""

    def __init__(self) -> None:
        self._custom: dict[str, CustomTool] = {}
        self._load_custom()

    # ── built-in tools ───────────────────────────────────────────────────

    def list_builtin(self) -> list[ToolInfo]:
        """Return metadata for all built-in tools, reflecting disabled state."""
        disabled = self._load_disabled_builtins()
        return [
            ToolInfo(
                name=t.__name__,
                description=(t.__doc__ or "").split("\n")[0][:120] if t.__doc__ else "",
                builtin=True,
                enabled=t.__name__ not in disabled,
            )
            for t in DEFAULT_TOOLS
        ]

    # ── all tools ────────────────────────────────────────────────────────

    def list_all(self) -> list[ToolInfo]:
        """Return all tools (built-in + custom), with custom overriding built-in."""
        builtins = {t.name: t for t in self.list_builtin()}
        # Custom tools can shadow built-in names.
        for name, ct in self._custom.items():
            builtins[name] = ct.to_info()
        return sorted(builtins.values(), key=lambda t: (not t.builtin, t.name))

    def list_enabled(self, cwd: str | None = None) -> list[Any]:
        """Return the actual tool objects for all enabled tools.

        Args:
            cwd: Workspace directory to run custom (shell-command) tools
                in. Built-in shell/editor tools are swapped for sandboxed
                versions separately by the session manager once a
                workspace is resolved; custom tools have no such swap
                step, so their workspace binding happens here instead.
        """
        auto_approve_tools()
        tools = []

        # Built-in tools.
        enabled_builtins = {t.name for t in self.list_builtin() if t.enabled}
        for t in DEFAULT_TOOLS:
            if t.__name__ in enabled_builtins:
                tools.append(t)

        # Custom tools.
        for ct in self._custom.values():
            if ct.enabled:
                tools.append(ct.to_strands_tool(cwd=cwd))

        return tools

    # ── custom tools CRUD ────────────────────────────────────────────────

    def get_custom(self, name: str) -> CustomTool | None:
        return self._custom.get(name)

    def add_custom(self, tool: CustomTool) -> None:
        if tool.name in {t.__name__ for t in DEFAULT_TOOLS}:
            raise ValueError(f"Tool {tool.name!r} shadows a built-in. Choose a different name.")
        if tool.name in self._custom:
            raise ValueError(f"Custom tool {tool.name!r} already exists.")
        tool.created_at = time.time()
        self._custom[tool.name] = tool
        self._save_custom()

    def update_custom(self, tool: CustomTool) -> None:
        if tool.name not in self._custom:
            raise ValueError(f"Custom tool {tool.name!r} not found.")
        self._custom[tool.name] = tool
        self._save_custom()

    def delete_custom(self, name: str) -> None:
        if name not in self._custom:
            raise ValueError(f"Custom tool {name!r} not found.")
        del self._custom[name]
        self._save_custom()

    def toggle_custom(self, name: str) -> CustomTool:
        """Toggle a custom tool's enabled state."""
        if name not in self._custom:
            raise ValueError(f"Custom tool {name!r} not found.")
        self._custom[name].enabled = not self._custom[name].enabled
        self._save_custom()
        return self._custom[name]

    def toggle_builtin(self, name: str) -> ToolInfo:
        """Toggle a built-in tool's enabled state (persisted as disabled override)."""
        disabled = self._load_disabled_builtins()
        if name in disabled:
            disabled.remove(name)
        else:
            disabled.add(name)
        self._save_disabled_builtins(disabled)

        info = ToolInfo(name=name, builtin=True, enabled=name not in disabled)
        return info

    # ── persistence ──────────────────────────────────────────────────────

    def _custom_path(self) -> Path:
        return Path(_settings_path()).parent / "tools.yaml"

    def _disabled_path(self) -> Path:
        return Path(_settings_path()).parent / "disabled_tools.yaml"

    def _load_custom(self) -> None:
        path = self._custom_path()
        if not path.exists():
            return
        try:
            data = yaml.safe_load(path.read_text()) or {}
            for name, d in data.items():
                self._custom[name] = CustomTool(
                    name=d["name"],
                    description=d.get("description", ""),
                    command=d.get("command", ""),
                    parameters=d.get("parameters", []),
                    enabled=d.get("enabled", True),
                    created_at=d.get("created_at", 0.0),
                )
        except (yaml.YAMLError, OSError, KeyError):
            pass

    def _save_custom(self) -> None:
        path = self._custom_path()
        data = {
            name: {
                "name": ct.name,
                "description": ct.description,
                "command": ct.command,
                "parameters": ct.parameters,
                "enabled": ct.enabled,
                "created_at": ct.created_at,
            }
            for name, ct in self._custom.items()
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(yaml.dump(data, default_flow_style=False))
        tmp.chmod(0o600)
        tmp.rename(path)

    def _load_disabled_builtins(self) -> set[str]:
        path = self._disabled_path()
        if not path.exists():
            return set()
        try:
            data = yaml.safe_load(path.read_text()) or {}
            return set(data.get("disabled", []))
        except (yaml.YAMLError, OSError):
            return set()

    def _save_disabled_builtins(self, disabled: set[str]) -> None:
        path = self._disabled_path()
        data = {"disabled": sorted(disabled)}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(yaml.dump(data, default_flow_style=False))
        tmp.chmod(0o600)
        tmp.rename(path)
