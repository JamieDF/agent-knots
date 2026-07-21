"""Project data models — workspaces that group tasks and sessions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Project:
    """A workspace — groups tasks, sessions, and settings."""
    id: str
    name: str
    description: str = ""
    repository: str = ""
    default_branch: str = "main"
    runtime: str = ""           # "inprocess", "subprocess", or "" (use global)
    tags: list[str] = field(default_factory=list)
    # Config-only for now — no scheduler enforces these yet. Surfaced on
    # the Dashboard's "Up next" queue per the Atelier design (auto-assign
    # toggle + max concurrent agents), real enforcement is a later phase.
    auto_assign: bool = False
    max_concurrent: int = 2
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
