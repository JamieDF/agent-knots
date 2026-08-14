"""Review — tasks sitting in the review workflow stage, and the
approve/reject flow for each one's file changes.

Diffs are still derived live from git (no separate capture/staging
layer) — pending diffs are just the task's branch's current uncommitted
changes in its workspace. Approve stages+commits a file (or everything
remaining); once nothing is left pending, the task is moved to done
(refused, staying in review, if acceptance criteria aren't met — the
commit itself still stands either way).

Git is optional throughout. A workspace can be a plain folder — for
writing, research, planning, or just a repo the user never initialised
— and its tasks still need reviewing. Every endpoint here resolves the
repo through _task_repo(), which returns None for those, and the flow
degrades to reviewing the task itself: no diffs to show, nothing to
stage, and approve/reject acting on the task's status alone. The review
gate is task logic (set_status refusing on unmet acceptance criteria),
so it works identically either way. Before this, a task in a non-git
workspace could enter review and never leave — approve and reject both
returned 400.

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
from agent_knots.project.models import resolve_finish
from agent_knots.project.store import ProjectStore
from agent_knots.task.lifecycle import maybe_fire_role_triggers, maybe_pause_or_stop_finished_sessions
from agent_knots.task.models import Task, TaskStatus
from agent_knots.task.store import TaskStore


def _task_or_404(task_id: str) -> Task:
    task = TaskStore(_tasks_dir()).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _task_repo(task: Task) -> Path | None:
    """The git repo a task's changes live in, or None if there isn't one.

    None covers every "there is nothing to diff" case — no workspace, a
    workspace with no repository, or a directory that simply isn't a git
    repo. All three are legitimate: a workspace can be a plain folder
    for writing, research or planning, and its tasks still go through
    review. Only the *task* not existing is an error, and that's
    _task_or_404's job.
    """
    if not task.project:
        return None
    proj = ProjectStore(_projects_dir()).get(task.project)
    if proj is None or not proj.repository:
        return None
    repo = Path(proj.repository)
    return repo if (repo / ".git").is_dir() else None


def _task_session(task: Task, session_manager: Any) -> Any:
    """The task's live writer session — still paused rather than
    stopped, unless something else disturbed it (see task/lifecycle.py).
    None if it isn't alive, e.g. after a server restart."""
    return next(
        (s for s in session_manager.active if s.task_id == task.id and not s.advisory), None,
    )


def _task_branch(task: Task, session: Any) -> str:
    """The branch a task's work is on, falling back to the
    deterministic name when there's no live session to ask."""
    return (session.branch if session and session.branch else None) or session_branch_name(
        task.id, task.title, "",
    )


def _require_repo(task: Task) -> Path:
    """_task_repo for the endpoints that genuinely can't work without
    git — fetching a specific file's diff."""
    repo = _task_repo(task)
    if repo is None:
        raise HTTPException(status_code=400, detail="Task's workspace is not a git repository")
    return repo


async def _maybe_finish_on_approve(task: Task, session_manager: Any) -> dict | None:
    """Merge or open a PR as part of approving, when the workspace is
    configured that way. None when it isn't, or when there's nothing to
    finish.

    Reuses the task routes' own handlers rather than reimplementing the
    preconditions — there is exactly one definition of "can this branch
    be finished", and two copies would drift.
    """
    from agent_knots.cockpit.web.routes.tasks import (
        finish_task_branch,
        task_finish_state,
    )

    proj = ProjectStore(_projects_dir()).get(task.project) if task.project else None
    action, when = resolve_finish(proj)
    if when != "on_approve" or action == "none":
        return None

    state = task_finish_state(task, session_manager)
    if not state["has_repo"] or state["commits_ahead"] == 0:
        return None

    return await finish_task_branch(task.id, action, session_manager)


def _feedback_message(approved_files: list[str], rejected_files: list[str], reason: str) -> str:
    parts = ["A human reviewed your changes."]
    if approved_files:
        parts.append(
            "These files were approved and already committed — leave them as they "
            f"are: {', '.join(approved_files)}."
        )
    if rejected_files:
        parts.append(f"These files were rejected: {', '.join(rejected_files)}. Reason: {reason}")
    else:
        # No file list to name — either a non-git workspace, or nothing
        # was pending. The rejection is of the work on the task itself,
        # and saying so beats "These files were rejected: ." with an
        # empty list where the agent expects filenames.
        parts.append(f"Your work on this task was rejected. Reason: {reason}")
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
            session = _task_session(task, session_manager)
            branch = _task_branch(task, session)
            proj = ProjectStore(_projects_dir()).get(task.project) if task.project else None

            # Diff stats — total file count + added/deleted across all
            # pending files. `has_repo` distinguishes "a git workspace
            # with nothing pending" from "nothing to diff in the first
            # place", which the UI needs: the former means the review is
            # already actioned, the latter means the review is of the
            # task itself and the file-based controls don't apply.
            repo = _task_repo(task)
            file_count = 0
            total_added = 0
            total_deleted = 0
            if repo is not None:
                stat = _git_diff_stat(repo)
                file_count = len(stat)
                total_added = sum(f["added"] for f in stat)
                total_deleted = sum(f["deleted"] for f in stat)

            items.append({
                "has_repo": repo is not None,
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
        repo = _task_repo(task)
        if repo is None:
            # Not an error — a non-git workspace has no diffs to list,
            # and the review screen renders the task on its own.
            return {"has_repo": False, "branch": None, "diffs": []}
        return {
            "has_repo": True,
            "branch": current_branch(repo),
            "diffs": [
                {"file": f["path"], "added": f["added"], "deleted": f["deleted"]}
                for f in _git_diff_stat(repo)
            ],
        }

    @router.get("/api/review/diff")
    async def get_review_diff(task_id: str = Query(...), file: str = Query(...)):
        task = _task_or_404(task_id)
        return {"diff": _git_diff_for_file(_require_repo(task), file)}

    @router.post("/api/review/approve")
    async def approve_review(body: ReviewApproveRequest):
        task = _task_or_404(body.task_id)
        if task.status != TaskStatus.REVIEW:
            raise HTTPException(status_code=400, detail="Task is not in review")

        repo = _task_repo(task)
        result: dict[str, Any] = {"status": "approved"}

        # Only stage and commit when there's actually something pending.
        # The branch check below guards against committing onto someone
        # else's checkout — but with nothing to commit there is nothing
        # to get wrong, and enforcing it anyway blocks two legitimate
        # cases: an agent that committed its own work to the branch, and
        # a freshly cloned repo whose task branches exist only as remote
        # refs (which is exactly what the playground ships).
        if repo is not None and _git_diff_stat(repo):
            branch = _task_branch(task, _task_session(task, session_manager))
            actual = current_branch(repo)
            if actual != branch:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Repo is on branch {actual!r} but this task's work belongs on "
                        f"{branch!r}, and there are uncommitted changes that would be "
                        "committed to the wrong place. Another session may have taken "
                        "over the workspace — refresh and try again."
                    ),
                )
            add_result = _run_git(repo, ["add", "--", body.file] if body.file else ["add", "-A"])
            if add_result.returncode != 0:
                raise HTTPException(status_code=500, detail=f"git add failed: {add_result.stderr.strip()}")
            commit_result = _run_git(repo, ["commit", "-m", "Approved via Review"])
            if commit_result.returncode != 0:
                raise HTTPException(status_code=500, detail=f"git commit failed: {commit_result.stderr.strip()}")
            result["status"] = "committed"

        # With no repo there is nothing to stage and nothing left
        # pending by definition, so approval closes the task out
        # immediately. The gate itself is task logic, not git logic:
        # set_status refusing on unmet acceptance criteria is what makes
        # this a real review either way.
        if repo is None or not _git_diff_stat(repo):
            store = TaskStore(_tasks_dir())
            old_status = task.status.value
            try:
                task = store.set_status(task.id, TaskStatus.DONE, actor="human")
            except ValueError as e:
                # Refused (unmet criteria) just means it stays in
                # review; any commit above still stands.
                result["task_status"] = "review"
                result["done_error"] = str(e)
            else:
                await maybe_pause_or_stop_finished_sessions(session_manager, task.status.value, task)
                maybe_fire_role_triggers(session_manager, old_status, task.status.value, task)
                result["task_status"] = task.status.value

                # Only now, after the stop above. Reaching review merely
                # *pauses* a session, and a paused session still holds
                # the repo (SessionManager._repo_writers) — so attempting
                # this any earlier would be refused every single time.
                # A failure here is reported but never un-does the
                # approval: the task is legitimately done either way,
                # and leaving it stuck in review because a merge
                # conflicted would be the worse outcome.
                finish = await _maybe_finish_on_approve(task, session_manager)
                if finish:
                    result["finish"] = finish
        return result

    @router.post("/api/review/reject")
    async def reject_review(body: ReviewRejectRequest):
        task = _task_or_404(body.task_id)
        if task.status != TaskStatus.REVIEW:
            raise HTTPException(status_code=400, detail="Task is not in review")
        repo = _task_repo(task)
        session = _task_session(task, session_manager)

        # No repo means no filenames to enumerate — the rejection is of
        # the task's work as a whole, which _feedback_message words
        # differently rather than handing the agent an empty list.
        if body.file:
            rejected_files = [body.file]
        elif repo is not None:
            rejected_files = [f["path"] for f in _git_diff_stat(repo)]
        else:
            rejected_files = []
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
