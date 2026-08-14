"""Workspace (Project) CRUD routes.

A workspace is "managed" when agent-knots created its directory under
config.workspaces_root() and therefore owns it — either by cloning a
repo there, or by making an empty folder. The alternative, and what
every workspace was before managed clones existed, is pointing
`repository` straight at a directory the user already had.

The distinction only ever governs who owns the path. `repository` still
means "the directory sessions work in" in both cases, so nothing
downstream of here has to care which kind it is.
"""

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import (
    CreateWorkspaceRequest,
    PushBranchRequest,
    UpdateWorkspaceRequest,
)
from agent_knots.config import projects_dir as _projects_dir
from agent_knots.config import tasks_dir as _tasks_dir
from agent_knots.config import workspaces_root as _workspaces_root
from agent_knots.gitutil import (
    clone_into_async,
    init_repo,
    push_branch_async,
    repo_name_from_source,
    unique_clone_dir,
)
from agent_knots.playground import ManifestError, has_manifest, read_manifest
from agent_knots.project.models import Project
from agent_knots.project.store import ProjectStore
from agent_knots.task.store import TaskStore


def _workspace_to_response(w: Project) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "repository": w.repository,
        "source": w.source,
        "managed": w.managed,
        "runtime": w.runtime,
        "provider": w.provider,
        "finish_action": w.finish_action,
        "finish_when": w.finish_when,
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


async def provision_managed_dir(source: str, workspace_id: str, init_git: bool = False) -> str:
    """Create the directory a managed workspace will live in.

    Clone `source` if given, otherwise make an empty folder. Returns the
    path. Raises HTTPException(400) on a failed clone, having cleaned up
    the partial directory first — provisioning happens before the
    workspace record exists precisely so a failure leaves neither half
    behind.

    Shared with the playground route, which needs exactly this and would
    otherwise reimplement it slightly differently.
    """
    dest = unique_clone_dir(
        _workspaces_root(), repo_name_from_source(source, fallback=workspace_id),
    )
    if source:
        result = await clone_into_async(source, dest)
        if not result.ok:
            shutil.rmtree(dest, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Clone failed: {result.failed_reason}")
        return result.path

    dest.mkdir(parents=True, exist_ok=True)
    if init_git:
        init_repo(dest)
    return str(dest)


def seed_from_manifest(repo: Path, workspace_id: str) -> int:
    """Import a playground repo's shipped tasks. Returns how many landed.

    A repo without a manifest is the normal case, not an error — this
    only ever fires for the demo playground. A repo *with* an unreadable
    one is worth failing loudly on, since the caller explicitly asked to
    seed and a silently empty board would be baffling.

    Tasks keep their original ids (see playground.read_manifest for why
    that matters), so re-importing the same repo into a second workspace
    would collide. Already-present ids are skipped rather than
    overwritten: whatever is on the board now is the user's, possibly
    with real progress on it.
    """
    if not has_manifest(repo):
        return 0

    try:
        tasks = read_manifest(repo, workspace_id)
    except ManifestError as e:
        raise HTTPException(status_code=400, detail=f"Playground manifest: {e}") from e

    store = TaskStore(_tasks_dir())
    seeded = 0
    for task in tasks:
        if store.get(task.id) is not None:
            continue
        store.create(task)
        seeded += 1
    return seeded


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
        """Create a new workspace.

        managed=true provisions the directory before the workspace
        record exists: clone `repository` if one was given, otherwise
        make an empty folder. Provisioning first means a failed clone
        leaves nothing behind at all — no half-made workspace pointing
        at a directory that isn't a usable repo.

        It defaults to false so existing API callers keep getting a
        path used verbatim. The create-workspace dialog passes true,
        which is what makes managed the default a user sees.
        """
        store = ProjectStore(_projects_dir())
        workspace_id = body.id or _unique_project_id(store, body.name)
        source = body.repository.strip()
        repository = source
        managed = body.managed

        # Checked up front rather than left to store.create()'s own
        # ValueError: by then we'd have already cloned, and the 409
        # would strand a directory nothing points at. Only reachable
        # when body.id was supplied — _unique_project_id can't collide.
        if store.get(workspace_id) is not None:
            raise HTTPException(
                status_code=409, detail=f"Workspace {workspace_id!r} already exists",
            )

        if managed:
            repository = await provision_managed_dir(source, workspace_id, body.init_git)

        ws = Project(
            id=workspace_id,
            name=body.name,
            description=body.description,
            repository=repository,
            source=source if managed else "",
            managed=managed,
            runtime=body.runtime,
            provider=body.provider,
            finish_action=body.finish_action,
            finish_when=body.finish_when,
            tags=body.tags,
            auto_assign=body.auto_assign,
            max_concurrent=body.max_concurrent,
        )
        store.create(ws)

        seeded = 0
        if body.seed_tasks and repository:
            seeded = seed_from_manifest(Path(repository), ws.id)

        return {
            "status": "ok", "id": ws.id, "repository": ws.repository,
            "managed": ws.managed, "seeded_tasks": seeded,
        }

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
            # A managed workspace's path is ours: we created it, we
            # clean it up, and sessions/branches/review all point into
            # it. Repointing would orphan real code on disk rather than
            # move anything, so it's refused outright.
            if ws.managed and body.repository != ws.repository:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "This workspace's folder is managed by agent-knots and can't be "
                        "repointed. Create a new workspace instead."
                    ),
                )
            ws.repository = body.repository
        if body.runtime is not None:
            ws.runtime = body.runtime
        if body.provider is not None:
            ws.provider = body.provider
        if body.finish_action is not None:
            ws.finish_action = body.finish_action
        if body.finish_when is not None:
            ws.finish_when = body.finish_when
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
    async def delete_workspace(workspace_id: str, delete_files: bool = Query(False)):
        """Delete a workspace record.

        The directory is left alone unless delete_files is passed, and
        even then only for a managed workspace. A managed clone holds
        real code that may not be pushed anywhere, and an unmanaged
        workspace's folder was never ours in the first place — same
        principle the wastebin applies to session working dirs.
        """
        store = ProjectStore(_projects_dir())
        ws = store.get(workspace_id)
        store.delete(workspace_id)

        removed_files = False
        if delete_files and ws is not None and ws.managed and ws.repository:
            shutil.rmtree(ws.repository, ignore_errors=True)
            removed_files = True
        return {"status": "ok", "removed_files": removed_files}

    @router.post("/api/workspaces/{workspace_id}/push")
    async def push_workspace_branch(workspace_id: str, body: PushBranchRequest):
        """Push a branch from this workspace to its remote.

        Deliberately separate from Review's approve: approving commits,
        and nothing leaves the machine until someone asks for it here.
        """
        store = ProjectStore(_projects_dir())
        ws = store.get(workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if not ws.repository:
            raise HTTPException(status_code=400, detail="Workspace has no repository")

        result = await push_branch_async(Path(ws.repository), body.branch, body.remote)
        if not result.ok:
            raise HTTPException(status_code=400, detail=f"Push failed: {result.failed_reason}")
        return {"status": "pushed", "branch": result.branch, "remote": result.remote}

    return router
