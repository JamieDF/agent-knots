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


def wastebin_dir() -> Path:
    """Directory where stopped-session tombstone records live — see
    wastebin.py. One YAML file per session, same layout as tasks_dir()."""
    return _ensure_dir(_home() / "wastebin")


def settings_file() -> Path:
    """Path to the YAML settings file."""
    return _home() / "settings.yaml"


def cockpit_token_file() -> Path:
    """Path to the web cockpit auth token file."""
    return _home() / "cockpit.token"


def worktrees_dir() -> Path:
    """Root directory for per-session git worktrees."""
    return _ensure_dir(_home() / "worktrees")


def session_workdir(session_id: str) -> Path:
    """A dedicated, isolated directory for a session that has no explicit
    working_dir and no project attached.

    Without this, such a session resolved to no working directory at
    all — which meant no sandbox, which meant its shell/editor tools
    fell back to strands_tools' raw, unbounded versions operating on
    wherever the agent-knots server process itself happened to be
    running from. Confirmed live: a workspace-less test session wrote a
    file straight into this project's own repo. Every session now gets
    somewhere real and contained to work instead — see
    SessionManager._resolve_working_dir.
    """
    return _ensure_dir(_home() / "workdirs" / session_id)


def stages_file() -> Path:
    """Path to the board-stages config YAML file (Workflows screen)."""
    return _home() / "stages.yaml"


def roles_file() -> Path:
    """Path to the default-agent-roles config YAML file (Workflows screen)."""
    return _home() / "roles.yaml"


def usage_file() -> Path:
    """Path to the append-only token/cost usage ledger (JSONL)."""
    return _home() / "usage.jsonl"


def policies_file() -> Path:
    """Path to the policy-rules config YAML file (Settings screen)."""
    return _home() / "policies.yaml"


def mcp_servers_file() -> Path:
    """Path to the MCP server registry config YAML file (Settings screen)."""
    return _home() / "mcp_servers.yaml"
