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


def db_path() -> Path:
    """Path to the SQLite database for tasks, projects, wastebin metadata, and usage."""
    return _home() / "state.db"


def vault_dir() -> Path:
    """Directory where the encrypted vault store lives."""
    return _ensure_dir(_home() / "vault")


def wastebin_dir() -> Path:
    """Directory for stopped-session event transcripts
    (`<id>.history.json`). Metadata lives in state.db — see wastebin.py."""
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


# The demo project the playground clones — a half-built colour palette
# generator, itself built with agent-knots so the tasks it ships are the
# real ones that built it.
#
# HTTPS on purpose. Anyone can clone this anonymously; the SSH form
# (git@github.com:...) needs a key on file and would fail for exactly
# the people the playground exists for — someone trying agent-knots for
# the first time.
DEFAULT_PLAYGROUND_REPO = "https://github.com/JamieDF/agent-knots-playground.git"


def playground_repo() -> str:
    """Where the playground is cloned from.

    AGENT_KNOTS_PLAYGROUND_REPO env → `playground_repo` in settings.yaml
    → DEFAULT_PLAYGROUND_REPO. The override exists so the flow can be
    pointed at a fork, or at a local path while developing against a
    repo that isn't published yet.
    """
    if env := os.environ.get("AGENT_KNOTS_PLAYGROUND_REPO"):
        return env

    # Deferred for the same circular-import reason as workspaces_root().
    from agent_knots.settings import load as _load_settings

    return _load_settings().playground_repo or DEFAULT_PLAYGROUND_REPO


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


def policies_file() -> Path:
    """Path to the policy-rules config YAML file (Settings screen)."""
    return _home() / "policies.yaml"


def mcp_servers_file() -> Path:
    """Path to the MCP server registry config YAML file (Settings screen)."""
    return _home() / "mcp_servers.yaml"
