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
    repository: str = ""           # git repo path
    default_branch: str = "main"
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
