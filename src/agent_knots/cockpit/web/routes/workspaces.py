"""Workspace (Project) CRUD routes."""

import re

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import CreateWorkspaceRequest, UpdateWorkspaceRequest
from agent_knots.config import projects_dir as _projects_dir
from agent_knots.project.models import Project
from agent_knots.project.store import ProjectStore


def _workspace_to_response(w: Project) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "repository": w.repository,
        "runtime": w.runtime,
        "tags": w.tags,
        "auto_assign": w.auto_assign,
        "max_concurrent": w.max_concurrent,
        "archived": w.archived,
        "created_at": w.created_at,
    }


def _unique_project_id(store: ProjectStore, name: str) -> str:
    """Slugify a workspace name into an id, deduping against existing
    workspaces — lets the create-workspace dialog drop the id field
    entirely and just ask for a name."""
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "workspace"
    candidate = base
    n = 2
    while store.get(candidate) is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/workspaces")
    async def list_workspaces(include_archived: bool = Query(False)):
        """List workspaces (projects). Archived workspaces are hidden by
        default — pass include_archived=true (Settings' management view) to
        see them too."""
        store = ProjectStore(_projects_dir())
        workspaces = store.list()
        if not include_archived:
            workspaces = [w for w in workspaces if not w.archived]
        return {"workspaces": [_workspace_to_response(w) for w in workspaces]}

    @router.get("/api/workspaces/{workspace_id}")
    async def get_workspace(workspace_id: str):
        """Get a single workspace's detail."""
        store = ProjectStore(_projects_dir())
        ws = store.get(workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return _workspace_to_response(ws)

    @router.post("/api/workspaces")
    @raises_as(409)
    async def create_workspace(body: CreateWorkspaceRequest):
        """Create a new workspace."""
        store = ProjectStore(_projects_dir())
        ws = Project(
            id=body.id or _unique_project_id(store, body.name),
            name=body.name,
            description=body.description,
            repository=body.repository,
            runtime=body.runtime,
            tags=body.tags,
            auto_assign=body.auto_assign,
            max_concurrent=body.max_concurrent,
        )
        store.create(ws)
        return {"status": "ok", "id": ws.id}

    @router.patch("/api/workspaces/{workspace_id}")
    async def update_workspace(workspace_id: str, body: UpdateWorkspaceRequest):
        """Update a workspace."""
        store = ProjectStore(_projects_dir())
        ws = store.get(workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if body.name is not None:
            ws.name = body.name
        if body.description is not None:
            ws.description = body.description
        if body.repository is not None:
            ws.repository = body.repository
        if body.runtime is not None:
            ws.runtime = body.runtime
        if body.tags is not None:
            ws.tags = body.tags
        if body.auto_assign is not None:
            ws.auto_assign = body.auto_assign
        if body.max_concurrent is not None:
            ws.max_concurrent = body.max_concurrent
        if body.archived is not None:
            ws.archived = body.archived
        store.update(ws)
        return {"status": "ok"}

    @router.delete("/api/workspaces/{workspace_id}")
    @raises_as(404)
    async def delete_workspace(workspace_id: str):
        """Delete a workspace."""
        store = ProjectStore(_projects_dir())
        store.delete(workspace_id)
        return {"status": "ok"}

    return router
