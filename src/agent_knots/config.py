"""Central configuration: paths, environment, and settings.

All filesystem state lives under AGENT_KNOTS_HOME (default: ~/.agent-knots).
"""

from __future__ import annotations

import os
from pathlib import Path


def _home() -> Path:
    """Return the agent-knots home directory, respecting AGENT_KNOTS_HOME env var."""
    if env := os.environ.get("AGENT_KNOTS_HOME"):
        return Path(env)
    return Path.home() / ".agent-knots"


def _ensure_dir(path: Path) -> Path:
    """Create the directory (and parents) if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---- public API ----

def sessions_dir() -> Path:
    """Directory where session records (.yaml), pid files, and sockets live."""
    return _ensure_dir(_home() / "sessions")


def projects_dir() -> Path:
    """Directory where project YAML files live."""
    return _ensure_dir(_home() / "projects")


def tasks_dir() -> Path:
    """Directory where task YAML files live."""
    return _ensure_dir(_home() / "tasks")


def vault_dir() -> Path:
    """Directory where the encrypted vault store lives."""
    return _ensure_dir(_home() / "vault")


def settings_file() -> Path:
    """Path to the YAML settings file."""
    return _home() / "settings.yaml"


def cockpit_token_file() -> Path:
    """Path to the web cockpit auth token file."""
    return _home() / "cockpit.token"


def worktrees_dir() -> Path:
    """Root directory for per-session git worktrees."""
    return _ensure_dir(_home() / "worktrees")
