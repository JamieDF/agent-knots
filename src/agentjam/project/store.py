"""YAML file-backed project store."""

from __future__ import annotations

import time
from pathlib import Path

import yaml

from agentjam.project.models import Project


class ProjectStore:
    """CRUD for projects, backed by YAML files."""

    def __init__(self, projects_dir: Path) -> None:
        self._dir = Path(projects_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        return self._dir / f"{project_id}.yaml"

    def create(self, project: Project) -> Project:
        path = self._path(project.id)
        if path.exists():
            raise ValueError(f"Project {project.id!r} already exists")
        project.created_at = time.time()
        project.updated_at = project.created_at
        self._save(project)
        return project

    def get(self, project_id: str) -> Project | None:
        path = self._path(project_id)
        if not path.exists():
            return None
        return self._load(path)

    def list(self) -> list[Project]:
        projects = []
        for path in sorted(self._dir.glob("*.yaml")):
            p = self._load(path)
            if p:
                projects.append(p)
        return projects

    def update(self, project: Project) -> Project:
        if not self._path(project.id).exists():
            raise ValueError(f"Project {project.id!r} not found")
        project.updated_at = time.time()
        self._save(project)
        return project

    def delete(self, project_id: str) -> None:
        path = self._path(project_id)
        if not path.exists():
            raise ValueError(f"Project {project_id!r} not found")
        path.unlink()

    def _save(self, project: Project) -> None:
        data = {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "repository": project.repository,
            "default_branch": project.default_branch,
            "tags": project.tags,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
        tmp = self._path(project.id).with_suffix(".tmp")
        tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        tmp.rename(self._path(project.id))

    def _load(self, path: Path) -> Project | None:
        try:
            data = yaml.safe_load(path.read_text())
            if not isinstance(data, dict):
                return None
            return Project(
                id=data["id"],
                name=data["name"],
                description=data.get("description", ""),
                repository=data.get("repository", ""),
                default_branch=data.get("default_branch", "main"),
                tags=data.get("tags", []),
                created_at=data.get("created_at", time.time()),
                updated_at=data.get("updated_at", time.time()),
            )
        except (yaml.YAMLError, OSError, KeyError):
            return None
