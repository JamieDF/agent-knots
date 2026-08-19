"""Playground routes — stand up the demo project in one click.

A new install is an empty board, so there's nothing to look at before
you've committed to setting a workspace up. The playground clones a real
half-built project (a colour palette generator, itself built with
agent-knots) whose repo ships the genuine tasks that built it: some
done, one waiting on review, some never started.

Separate from the workspace routes rather than a pre-filled
POST /api/workspaces, for two reasons. The frontend would otherwise have
to hardcode a repo URL that belongs in config. And reset here removes
things a normal workspace DELETE deliberately refuses to touch — the
tasks and the folder — which is only safe because this is a demo the
user asked for and can re-clone at will.
"""

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from agent_knots.cockpit.web.routes.workspaces import (
    provision_managed_dir,
    seed_from_manifest,
)
from agent_knots.config import playground_repo as _playground_repo
from agent_knots.project.models import Project
from agent_knots.storage import project_store, task_store

# Fixed so the UI can find it again to report on and reset it. A user
# who wants a second copy can clone the repo as an ordinary workspace.
PLAYGROUND_ID = "playground"
PLAYGROUND_NAME = "Palette Playground"
PLAYGROUND_DESCRIPTION = (
    "A half-built colour palette generator, built with agent-knots. "
    "The tasks on this board are the real ones that built it."
)


def _task_counts(project_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in task_store().list(project=project_id):
        counts[task.status.value] = counts.get(task.status.value, 0) + 1
    return counts


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/playground")
    async def playground_status():
        """Whether the playground is set up, and where it comes from.

        Lets the Settings card and the Dashboard's empty state render
        the right thing without inferring it from the workspace list.
        """
        ws = project_store().get(PLAYGROUND_ID)
        return {
            "exists": ws is not None,
            "workspace_id": PLAYGROUND_ID,
            "repo": _playground_repo(),
            "repository": ws.repository if ws else "",
            "task_counts": _task_counts(PLAYGROUND_ID) if ws else {},
        }

    @router.post("/api/playground")
    async def create_playground():
        """Clone the demo project and seed the tasks that built it."""
        store = project_store()
        if store.get(PLAYGROUND_ID) is not None:
            raise HTTPException(
                status_code=409,
                detail="The playground already exists. Reset it first to start over.",
            )

        source = _playground_repo()
        repository = await provision_managed_dir(source, PLAYGROUND_ID)

        ws = Project(
            id=PLAYGROUND_ID,
            name=PLAYGROUND_NAME,
            description=PLAYGROUND_DESCRIPTION,
            repository=repository,
            source=source,
            managed=True,
        )
        store.create(ws)

        seeded = seed_from_manifest(Path(repository), PLAYGROUND_ID)
        return {
            "status": "ok",
            "workspace_id": ws.id,
            "repository": ws.repository,
            "seeded_tasks": seeded,
            "task_counts": _task_counts(PLAYGROUND_ID),
        }

    @router.delete("/api/playground")
    async def reset_playground():
        """Remove the playground entirely — workspace, tasks and folder.

        Deliberately more destructive than deleting an ordinary managed
        workspace, which keeps its directory because it may hold work
        that was never pushed. Everything here came from a public repo
        and can be cloned again, so the useful behaviour is a clean
        teardown that leaves nothing to tidy up by hand.
        """
        store = project_store()
        ws = store.get(PLAYGROUND_ID)
        if ws is None:
            raise HTTPException(status_code=404, detail="No playground to reset")

        tasks = task_store()
        removed = 0
        for task in tasks.list(project=PLAYGROUND_ID):
            tasks.delete(task.id)
            removed += 1

        # Guarded on `managed` even though this route only ever creates
        # managed workspaces: if someone hand-edited the record to point
        # at their own checkout, that folder is not ours to delete.
        if ws.managed and ws.repository:
            shutil.rmtree(ws.repository, ignore_errors=True)
        store.delete(PLAYGROUND_ID)

        return {"status": "ok", "removed_tasks": removed}

    return router
