"""Review queue API (post-hoc diffs derived live from git).

No separate diff-capture/staging layer — pending diffs are just each
configured workspace's current uncommitted git changes, per
WORKPLAN.md's Phase 4 decoupling note. Approve stages+commits a
specific file (or everything pending, for approve-all). Reject
deliberately does NOT discard the changes — git checkout/reset/clean
against a real repo is a destructive action this won't automate; it
only acknowledges, matching the design's own "Rejected — agent
notified" copy (notifies, doesn't destroy).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.models import ReviewActionRequest
from agent_knots.config import projects_dir as _projects_dir
from agent_knots.gitutil import _git_diff_for_file, _git_diff_stat, _run_git
from agent_knots.project.store import ProjectStore


def _review_repo_or_404(workspace_id: str) -> Path:
    proj = ProjectStore(_projects_dir()).get(workspace_id)
    if proj is None or not proj.repository:
        raise HTTPException(status_code=404, detail="Workspace not found")
    repo = Path(proj.repository)
    if not (repo / ".git").is_dir():
        raise HTTPException(status_code=400, detail="Not a git repository")
    return repo


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/review/diffs")
    async def list_review_diffs():
        items = []
        for p in ProjectStore(_projects_dir()).list():
            if not p.repository:
                continue
            repo = Path(p.repository)
            if not (repo / ".git").is_dir():
                continue
            for f in _git_diff_stat(repo):
                items.append({
                    "workspace": p.id, "workspace_name": p.name,
                    "file": f["path"], "added": f["added"], "deleted": f["deleted"],
                })
        return {"diffs": items}

    @router.get("/api/review/diff")
    async def get_review_diff(workspace: str = Query(...), file: str = Query(...)):
        proj = ProjectStore(_projects_dir()).get(workspace)
        if proj is None or not proj.repository:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return {"diff": _git_diff_for_file(Path(proj.repository), file)}

    @router.post("/api/review/approve")
    async def approve_review(body: ReviewActionRequest):
        repo = _review_repo_or_404(body.workspace)
        add_result = _run_git(repo, ["add", "--", body.file] if body.file else ["add", "-A"])
        if add_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git add failed: {add_result.stderr.strip()}")
        commit_result = _run_git(repo, ["commit", "-m", "Approved via cockpit Review queue"])
        if commit_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git commit failed: {commit_result.stderr.strip()}")
        return {"status": "committed"}

    @router.post("/api/review/reject")
    async def reject_review(body: ReviewActionRequest):
        _review_repo_or_404(body.workspace)  # validates the workspace exists
        return {"status": "rejected", "note": "Not discarded — reject only acknowledges."}

    return router
