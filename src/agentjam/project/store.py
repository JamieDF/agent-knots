"""YAML file-backed project store.

Projects are multi-repo workspaces. Each project is a YAML file in
~/.agentjam/projects/.
"""

from __future__ import annotations

from pathlib import Path


class ProjectStore:
    """CRUD operations for projects, backed by YAML files on disk."""

    def __init__(self, projects_dir: Path) -> None:
        self.projects_dir = Path(projects_dir)

    def list(self) -> list[dict]:
        """List all projects. Not yet implemented."""
        return []

    def get(self, project_id: str) -> dict | None:
        """Get a single project by ID. Not yet implemented."""
        return None
