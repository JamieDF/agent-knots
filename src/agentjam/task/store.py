"""YAML file-backed task store.

Tasks are structured work items with acceptance criteria, progress logs,
and step tracking.
"""

from __future__ import annotations

from pathlib import Path


class TaskStore:
    """CRUD operations for tasks, backed by YAML files on disk."""

    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = Path(tasks_dir)

    def list(self) -> list[dict]:
        """List all tasks. Not yet implemented."""
        return []

    def get(self, task_id: str) -> dict | None:
        """Get a single task by ID. Not yet implemented."""
        return None
