"""Review — tasks sitting in the review workflow stage, and the
approve/reject flow for each one's file changes.

Diffs are still derived live from git (no separate capture/staging
layer) — pending diffs are just the task's branch's current uncommitted
changes in its workspace. Approve stages+commits a file (or everything
remaining); once nothing is left pending, the task is moved to done
(refused, staying in review, if acceptance criteria aren't met — the
commit itself still stands either way).

Reject is a real "send it back" action here, unlike the old
workspace-wide diff queue this replaced (which only acknowledged): it
logs why, moves the task back to in_progress, and resumes the task's
session with the feedback. The session is paused, not stopped, when a
task enters review (see task/lifecycle.py) specifically so this can
pick the *same* conversation back up instead of losing all context and
starting fresh — falls back to starting a new session only if the old
one isn't alive for some other reason (e.g. a server restart since it
paused).
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.models import ReviewApproveRequest, ReviewRejectRequest
from agent_knots.config import projects_dir as _projects_dir, tasks_dir as _tasks_dir
from agent_knots.gitutil import _git_diff_for_file, _git_diff_stat, _run_git, current_branch, session_branch_name
from agent_knots.project.store import ProjectStore
from agent_knots.task.lifecycle import maybe_fire_role_triggers, maybe_pause_or_stop_finished_sessions
from agent_knots.task.models import Task, TaskStatus
from agent_knots.task.store import TaskStore


def _task_or_404(task_id: str) -> Task:
    task = TaskStore(_tasks_dir()).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _task_repo_and_branch(task: Task, session_manager: Any) -> tuple[Path, str, Any]:
    """Resolve a review task's repo, expected branch, and live writer
    session (still paused, not stopped, if nothing else has disturbed
    it — see task/lifecycle.py). Falls back to the deterministic branch
    name if there's no live session for some reason."""
    if not task.project:
        raise HTTPException(status_code=400, detail="Task has no workspace")
    proj = ProjectStore(_projects_dir()).get(task.project)
    if proj is None or not proj.repository:
        raise HTTPException(status_code=404, detail="Workspace not found")
    repo = Path(proj.repository)
    if not (repo / ".git").is_dir():
        raise HTTPException(status_code=400, detail="Not a git repository")
    session = next(
        (s for s in session_manager.active if s.task_id == task.id and not s.advisory), None,
    )
    branch = (session.branch if session and session.branch else None) or session_branch_name(task.id, task.title, "")
    return repo, branch, session


def _feedback_message(approved_files: list[str], rejected_files: list[str], reason: str) -> str:
    parts = ["A human reviewed your changes."]
    if approved_files:
        parts.append(
            "These files were approved and already committed — leave them as they "
            f"are: {', '.join(approved_files)}."
        )
    parts.append(f"These files were rejected: {', '.join(rejected_files)}. Reason: {reason}")
    parts.append("Please address the feedback and continue the task.")
    return " ".join(parts)


def create_router(session_manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/review/tasks")
    async def list_review_tasks():
        """Tasks sitting in review, each with the workspace/branch its
        diffs live on, its (still paused, usually) session, and a
        summary of pending changes (file count + total +/- lines) so the
        review list can show what changed without a second fetch per
        task."""
        tasks = TaskStore(_tasks_dir()).list(status="review")
        items = []
        for task in tasks:
            session = next(
                (s for s in session_manager.active if s.task_id == task.id and not s.advisory), None,
            )
            branch = (session.branch if session and session.branch else None) or session_branch_name(task.id, task.title, "")
            proj = ProjectStore(_projects_dir()).get(task.project) if task.project else None

            # Diff stats — total file count + added/deleted across all
            # pending files. Best-effort: if the repo/branch isn't
            # resolvable (e.g. workspace removed), zeros rather than 500.
            file_count = 0
            total_added = 0
            total_deleted = 0
            try:
                repo, _br, _sess = _task_repo_and_branch(task, session_manager)
                stat = _git_diff_stat(repo)
                file_count = len(stat)
                total_added = sum(f["added"] for f in stat)
                total_deleted = sum(f["deleted"] for f in stat)
            except HTTPException:
                pass

            items.append({
                "id": task.id,
                "title": task.title,
                "priority": task.priority.value,
                "project": task.project,
                "project_name": proj.name if proj else "",
                "branch": branch,
                "session_id": session.id if session else None,
                "session_name": session.name if session else "",
                "session_running": bool(session and session.running),
                "session_error": (session._last_error if session else ""),
                "file_count": file_count,
                "added": total_added,
                "deleted": total_deleted,
            })
        return {"tasks": items}

    @router.get("/api/review/diffs")
    async def list_review_diffs(task_id: str = Query(...)):
        task = _task_or_404(task_id)
        repo, _branch, _session = _task_repo_and_branch(task, session_manager)
        return {
            "branch": current_branch(repo),
            "diffs": [
                {"file": f["path"], "added": f["added"], "deleted": f["deleted"]}
                for f in _git_diff_stat(repo)
            ],
        }

    @router.get("/api/review/diff")
    async def get_review_diff(task_id: str = Query(...), file: str = Query(...)):
        task = _task_or_404(task_id)
        repo, _branch, _session = _task_repo_and_branch(task, session_manager)
        return {"diff": _git_diff_for_file(repo, file)}

    @router.post("/api/review/approve")
    async def approve_review(body: ReviewApproveRequest):
        task = _task_or_404(body.task_id)
        if task.status != TaskStatus.REVIEW:
            raise HTTPException(status_code=400, detail="Task is not in review")
        repo, branch, _session = _task_repo_and_branch(task, session_manager)
        actual = current_branch(repo)
        if actual != branch:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Repo is now on branch {actual!r}, expected {branch!r} — "
                    "another session likely took over this workspace. Refresh and try again."
                ),
            )
        add_result = _run_git(repo, ["add", "--", body.file] if body.file else ["add", "-A"])
        if add_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git add failed: {add_result.stderr.strip()}")
        commit_result = _run_git(repo, ["commit", "-m", "Approved via Review"])
        if commit_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git commit failed: {commit_result.stderr.strip()}")

        result: dict[str, Any] = {"status": "committed"}
        if not _git_diff_stat(repo):
            # Nothing left pending on this task — try to close it out.
            # Refused (unmet criteria) just means it stays in review;
            # the commit above still stands either way.
            store = TaskStore(_tasks_dir())
            old_status = task.status.value
            try:
                task = store.set_status(task.id, TaskStatus.DONE, actor="human")
            except ValueError as e:
                result["task_status"] = "review"
                result["done_error"] = str(e)
            else:
                await maybe_pause_or_stop_finished_sessions(session_manager, task.status.value, task)
                maybe_fire_role_triggers(session_manager, old_status, task.status.value, task)
                result["task_status"] = task.status.value
        return result

    @router.post("/api/review/reject")
    async def reject_review(body: ReviewRejectRequest):
        task = _task_or_404(body.task_id)
        if task.status != TaskStatus.REVIEW:
            raise HTTPException(status_code=400, detail="Task is not in review")
        repo, _branch, session = _task_repo_and_branch(task, session_manager)

        rejected_files = [body.file] if body.file else [f["path"] for f in _git_diff_stat(repo)]
        message = _feedback_message(body.approved_files, rejected_files, body.reason)

        store = TaskStore(_tasks_dir())
        old_status = task.status.value
        task = store.set_status(task.id, TaskStatus.IN_PROGRESS, actor="human")
        maybe_fire_role_triggers(session_manager, old_status, task.status.value, task)

        if session is not None:
            await session_manager.set_mode(session.id, "agent")
            await session_manager.send(session.id, message)
            resumed_session_id = session.id
        else:
            resumed = await session_manager.start(
                mode="agent", task_id=task.id, project_id=task.project or None,
                task_description=message,
            )
            resumed_session_id = resumed.id

        return {"status": "rejected", "task_status": task.status.value, "session_id": resumed_session_id}

    return router
