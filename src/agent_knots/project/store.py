"""Project serialization helpers and SQLite-backed store."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_knots.project.models import Project
from agent_knots.storage.db import get_connection


def project_to_dict(project: Project) -> dict[str, Any]:
    """Project -> plain dict for JSON storage."""
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "repository": project.repository,
        "source": project.source,
        "managed": project.managed,
        "default_branch": project.default_branch,
        "runtime": project.runtime,
        "provider": project.provider,
        "finish_action": project.finish_action,
        "finish_when": project.finish_when,
        "tags": project.tags,
        "auto_assign": project.auto_assign,
        "max_concurrent": project.max_concurrent,
        "archived": project.archived,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def project_from_dict(data: dict[str, Any]) -> Project:
    return Project(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        repository=data.get("repository", ""),
        source=data.get("source", ""),
        managed=data.get("managed", False),
        default_branch=data.get("default_branch", "main"),
        runtime=data.get("runtime", ""),
        provider=data.get("provider", ""),
        finish_action=data.get("finish_action", ""),
        finish_when=data.get("finish_when", ""),
        tags=data.get("tags", []),
        auto_assign=data.get("auto_assign", False),
        max_concurrent=data.get("max_concurrent", 2),
        archived=data.get("archived", False),
        created_at=data.get("created_at", time.time()),
        updated_at=data.get("updated_at", time.time()),
    )


class ProjectStore:
    """SQLite-backed CRUD store for projects."""

    def __init__(self, db_path: Path) -> None:
        self._conn = get_connection(db_path)

    def create(self, project: Project) -> Project:
        if self.get(project.id) is not None:
            raise ValueError(f"Project {project.id!r} already exists")
        project.created_at = time.time()
        project.updated_at = project.created_at
        self._save(project)
        return project

    def get(self, project_id: str) -> Project | None:
        row = self._conn.execute(
            "SELECT data FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return self._load_json(row[0])

    def list(self) -> list[Project]:
        rows = self._conn.execute(
            "SELECT data FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        projects = []
        for row in rows:
            p = self._load_json(row[0])
            if p:
                projects.append(p)
        return projects

    def update(self, project: Project) -> Project:
        if self.get(project.id) is None:
            raise ValueError(f"Project {project.id!r} not found")
        project.updated_at = time.time()
        self._save(project)
        return project

    def delete(self, project_id: str) -> None:
        if self.get(project_id) is None:
            raise ValueError(f"Project {project_id!r} not found")
        self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()

    def _save(self, project: Project) -> None:
        data = json.dumps(project_to_dict(project))
        self._conn.execute(
            """
            INSERT INTO projects (id, archived, updated_at, data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                archived = excluded.archived,
                updated_at = excluded.updated_at,
                data = excluded.data
            """,
            (
                project.id,
                1 if project.archived else 0,
                project.updated_at,
                data,
            ),
        )
        self._conn.commit()

    def _load_json(self, raw: str) -> Project | None:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            return project_from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None
