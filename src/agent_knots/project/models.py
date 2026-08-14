"""Project data models — workspaces that group tasks and sessions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


def resolve_finish(project: Project | None) -> tuple[str, str]:
    """(finish_action, finish_when) for a workspace, falling back to the
    global settings when either is unset — and for a task with no
    workspace at all, which resolves entirely from globals.

    One function so the precedence lives in exactly one place; the route
    layer and the approve path both need the same answer and must not
    drift.
    """
    from agent_knots import settings as settings_mod

    s = settings_mod.load()
    action = (project.finish_action if project else "") or s.finish_action
    when = (project.finish_when if project else "") or s.finish_when
    return action, when


@dataclass
class Project:
    """A workspace — groups tasks, sessions, and settings."""
    id: str
    name: str
    description: str = ""
    # The working path, in both managed and unmanaged workspaces. Every
    # consumer (session cwd resolution, review, gitutil, the system
    # prompt) reads this and only this — `managed` changes who created
    # the directory, never what the field means.
    repository: str = ""
    # What the user originally gave us: a clone URL, or the local path
    # we cloned from. Empty for an unmanaged workspace (where
    # `repository` *is* what they gave us) or a managed one created
    # empty.
    source: str = ""
    # True when `repository` is a clone agent-knots created under
    # config.workspaces_root() and therefore owns. Governs whether we're
    # allowed to repoint or delete it.
    managed: bool = False
    default_branch: str = "main"
    runtime: str = ""           # "inprocess" or "" (use global)
    provider: str = ""          # named provider profile, or "" (use global)
    # How this workspace's tasks get finished once approved, "" = use the
    # global default. Not a matter of taste: "merge" suits a solo local
    # repo, "pull_request" a team repo whose mainline is protected —
    # merging locally into a protected branch simply fails on push.
    finish_action: str = ""     # merge | pull_request | none, or "" (global)
    finish_when: str = ""       # manual | on_approve, or "" (global)
    tags: list[str] = field(default_factory=list)
    # Config-only for now — no scheduler enforces these yet. Surfaced on
    # the Dashboard's "Up next" queue per the Atelier design (auto-assign
    # toggle + max concurrent agents), real enforcement is a later phase.
    auto_assign: bool = False
    max_concurrent: int = 2
    archived: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
