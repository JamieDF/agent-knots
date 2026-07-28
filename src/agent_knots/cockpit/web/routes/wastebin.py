"""Wastebin API — stopped-session tombstones, browsable and deletable.

Needs session_manager (unlike vault/tasks-adjacent routers that just
construct their own store) for the protected-branches check: since
branches are task-scoped, more than one wastebin entry can reference
the same branch, and a currently-active session might too — deleting
one entry must never force-delete a branch another entry or a live
session still legitimately points at.
"""

from fastapi import APIRouter

from agent_knots import settings
from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.config import wastebin_dir
from agent_knots.session.manager import SessionManager
from agent_knots.wastebin import WastebinStore


def _entry_to_response(e) -> dict:
    return {
        "session_id": e.session_id,
        "task_id": e.task_id,
        "task_title": e.task_title,
        "project_id": e.project_id,
        "branch": e.branch,
        "working_dir": e.working_dir,
        "is_auto_workdir": e.is_auto_workdir,
        "role": e.role,
        "advisory": e.advisory,
        "model": e.model,
        "tokens_used": e.tokens_used,
        "cost_usd": e.cost_usd,
        "started_at": e.started_at,
        "stopped_at": e.stopped_at,
    }


def create_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter()

    def _active_branches() -> set[str]:
        return {s.branch for s in session_manager.active if s.branch}

    @router.get("/api/wastebin")
    async def list_wastebin():
        store = WastebinStore(wastebin_dir())
        retention_days = settings.load().wastebin.retention_days
        entries = store.list(retention_days=retention_days, protected_branches=_active_branches())
        return {"entries": [_entry_to_response(e) for e in entries]}

    @router.delete("/api/wastebin/{session_id}")
    @raises_as(404)
    async def delete_wastebin_entry(session_id: str):
        store = WastebinStore(wastebin_dir())
        # Every other entry's branch is protected too — deleting one
        # entry must never force-delete a branch a different, still-kept
        # entry references (e.g. a task stopped, resumed, and stopped
        # again leaves two entries pointing at the same branch).
        protected = {
            e.branch for e in store.list() if e.branch and e.session_id != session_id
        }
        protected |= _active_branches()
        store.delete(session_id, protected_branches=protected)
        return {"status": "ok"}

    return router
