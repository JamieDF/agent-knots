"""Filesystem browse API (workspace folder picker).

This is a local-first, single-user app that already lets you point a
workspace at any local path and run shell commands in it — browsing
directory names isn't a new trust boundary on top of that, but it's
still directories-only (no file contents) and confined to what the
local user running the server can already see.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.gitutil import _github_url_from_remote, _run_git


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/fs/browse")
    async def browse_fs(path: str = Query("")):
        base = Path(path).expanduser() if path else Path.home()
        try:
            base = base.resolve()
        except OSError:
            raise HTTPException(status_code=400, detail="Invalid path")
        if not base.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        try:
            children = sorted(
                (c for c in base.iterdir() if c.is_dir() and not c.name.startswith(".")),
                key=lambda c: c.name.lower(),
            )
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        entries = [
            {"name": c.name, "path": str(c), "is_git": (c / ".git").exists()}
            for c in children
        ]
        parent = str(base.parent) if base.parent != base else None
        return {"path": str(base), "parent": parent, "entries": entries}

    @router.get("/api/fs/git-info")
    async def fs_git_info(path: str = Query(...)):
        repo = Path(path).expanduser()
        if not (repo / ".git").exists():
            return {"is_git": False, "github_url": None}
        result = _run_git(repo, ["remote", "get-url", "origin"])
        if result.returncode != 0:
            return {"is_git": True, "github_url": None}
        return {"is_git": True, "github_url": _github_url_from_remote(result.stdout.strip())}

    return router
