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


def workspaces_root() -> Path:
    """Root directory holding agent-knots-managed workspace clones.

    The one path in this module that deliberately lives OUTSIDE _home().
    Everything else here is internal state the user never opens by hand;
    a managed workspace is their actual code, so it goes somewhere
    visible and browsable rather than buried in a dotfolder.

    Resolution order:

      1. AGENT_KNOTS_WORKSPACES_ROOT — explicit override, wins outright.
      2. `workspaces_root` in settings.yaml — the Settings screen.
      3. <AGENT_KNOTS_HOME>/workspaces, but only when AGENT_KNOTS_HOME is
         explicitly set. Tests isolate by pointing AGENT_KNOTS_HOME at a
         tmp_path; without this rule the workspaces root would escape
         that sandbox (it isn't under _home()) and they'd clone into the
         real ~/agent-knots/workspaces. Tying the two together means
         every existing fixture keeps isolating for free.
      4. ~/agent-knots/workspaces — the default a real user gets, since
         they don't set AGENT_KNOTS_HOME.
    """
    if env := os.environ.get("AGENT_KNOTS_WORKSPACES_ROOT"):
        return _ensure_dir(Path(env))

    # Deferred import: settings.py imports this module, so a top-level
    # import here would be circular. Same idiom as session/manager.py.
    from agent_knots.settings import load as _load_settings

    configured = _load_settings().workspaces_root
    if configured:
        return _ensure_dir(Path(configured).expanduser())

    if os.environ.get("AGENT_KNOTS_HOME"):
        return _ensure_dir(_home() / "workspaces")

    return _ensure_dir(Path.home() / "agent-knots" / "workspaces")


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
