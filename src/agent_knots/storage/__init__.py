"""Central store factories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_knots.config import db_path
from agent_knots.storage.db import close_connection

if TYPE_CHECKING:
    from agent_knots.project.store import ProjectStore
    from agent_knots.task.store import TaskStore

_task_store: TaskStore | None = None
_project_store: ProjectStore | None = None


def task_store() -> TaskStore:
    """Return the shared TaskStore."""
    global _task_store
    from agent_knots.task.store import TaskStore

    if _task_store is None:
        _task_store = TaskStore(db_path())
    return _task_store


def project_store() -> ProjectStore:
    """Return the shared ProjectStore."""
    global _project_store
    from agent_knots.project.store import ProjectStore

    if _project_store is None:
        _project_store = ProjectStore(db_path())
    return _project_store


def reset_stores() -> None:
    """Clear cached store instances and close the DB connection (tests only)."""
    global _task_store, _project_store
    _task_store = None
    _project_store = None
    close_connection()
