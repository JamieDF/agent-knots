"""Task CRUD routes, including status/assign, criteria toggling, and
agent-assisted drafting. Also owns the role-trigger auto-start logic
that fires when a task's status transition crosses a workflow stage
boundary (Workflows screen)."""

import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.jsonutil import _extract_json_object
from agent_knots.cockpit.web.models import (
    CreateTaskRequest, DraftTaskRequest, ToggleCriterionRequest, UpdateTaskRequest,
)
from agent_knots import provider as provider_module
from agent_knots.gitutil import (
    ahead_of_remote,
    branch_exists,
    commits_ahead,
    delete_branch_force,
    merge_branch_async,
    open_pull_request_async as open_pr_async,
    push_branch_async,
    session_branch_name,
)
from agent_knots.project.models import resolve_finish
from agent_knots.storage import project_store, task_store
from agent_knots.session.manager import SessionManager
from agent_knots.task.lifecycle import maybe_pause_or_stop_finished_sessions, maybe_fire_role_triggers
from agent_knots.task.models import (
    Priority, ProgressEntry, ReviewGate, Step, Task, TaskStatus, new_task_id,
)
from agent_knots.task.store import TaskStore


def _task_to_response(task: Task, store: TaskStore | None = None) -> dict:
    """Serialize a Task to a JSON-safe dict.

    store is optional only so call sites that truly have no TaskStore
    handy (none currently) don't break — when given, unmet_dependencies
    is computed for real; without it, dependencies are reported as if
    none were unmet (better than raising, since this is just a display
    field, not enforcement — enforcement lives in TaskStore itself).
    """
    unmet = store.unmet_dependencies(task) if store is not None else []
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "tags": task.tags,
        "project": task.project,
        "review_gate": task.review_gate.value,
        "assigned_to": task.assigned_to,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "acceptance_criteria": task.acceptance_criteria,
        "criteria_met": task.criteria_met,
        "out_of_scope": task.out_of_scope,
        "dependencies": task.dependencies,
        "unmet_dependencies": [{"id": t.id, "title": t.title} for t in unmet],
        "required_credentials": task.required_credentials,
        "merged_into": task.merged_into,
        "pull_request_url": task.pull_request_url,
        "steps": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status.value,
                "notes": s.notes,
                "sub_steps": [
                    {"id": ss.id, "title": ss.title, "status": ss.status.value, "notes": ss.notes}
                    for ss in s.sub_steps
                ],
            }
            for s in task.steps
        ],
        "progress": [
            {
                "timestamp": p.timestamp,
                "status": p.status.value,
                "entry": p.entry,
                "actions_taken": p.actions_taken,
                "blocker": {
                    "description": p.blocker.description,
                    "question": p.blocker.question,
                    "options": p.blocker.options,
                    "awaiting": p.blocker.awaiting,
                } if p.blocker else None,
                "resolution": p.resolution,
                "next_step": p.next_step,
                "caller": p.caller,
            }
            for p in task.progress
        ],
    }


def task_finish_state(task: Task, session_manager: SessionManager) -> dict:
    """What, if anything, is left to do with this task's branch.

    `finish_action` is resolved here rather than in the UI so the button
    and the route can't disagree about what a workspace is set up to do.
    `commits_ahead` is what tells the difference between "nothing to
    merge" and "merged already" — both of which mean no button, for
    different reasons.
    """
    state = {"has_repo": False, "commits_ahead": 0, "finish_action": "none", "branch": ""}
    if not task.project:
        return state

    proj = project_store().get(task.project)
    if proj is None or not proj.repository:
        return state
    repo = Path(proj.repository)
    if not (repo / ".git").is_dir():
        return state

    action, _when = resolve_finish(proj)
    session = next(
        (s for s in session_manager.active if s.task_id == task.id and not s.advisory), None,
    )
    branch = (session.branch if session and session.branch else None) or session_branch_name(
        task.id, task.title, "",
    )
    base = proj.default_branch or "main"
    ahead = commits_ahead(repo, branch, base) if branch_exists(repo, branch) else 0

    state.update({
        "has_repo": True,
        "branch": branch,
        "base": base,
        "finish_action": action,
        "commits_ahead": max(ahead, 0),
    })
    return state


def _finishable(task_id: str, store: TaskStore, session_manager: SessionManager):
    """Shared preconditions for merge and pull-request.

    Returns (task, project, repo, branch) or raises. The writer-lock
    check is the important one: both operations move or publish the
    branch, and doing that under a live session would fight the very
    invariant _repo_writers exists to protect.
    """
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.project:
        raise HTTPException(status_code=400, detail="Task has no workspace")

    proj = project_store().get(task.project)
    if proj is None or not proj.repository:
        raise HTTPException(status_code=404, detail="Workspace not found")
    repo = Path(proj.repository)
    if not (repo / ".git").is_dir():
        raise HTTPException(status_code=400, detail="Workspace is not a git repository")

    owner = session_manager._repo_writers.get(str(repo))
    if owner is not None and owner in session_manager._sessions:
        raise HTTPException(
            status_code=409,
            detail=(
                "A session is still working in this workspace. Let it finish, or stop "
                "it, before moving its branch."
            ),
        )

    state = task_finish_state(task, session_manager)
    branch = state["branch"]
    if not branch_exists(repo, branch):
        raise HTTPException(status_code=400, detail=f"No branch {branch!r} to finish")
    return task, proj, repo, branch


async def _merge_task_branch(task_id: str, session_manager: SessionManager) -> dict:
    """Merge a finished task's branch into the workspace's base branch.

    Lives on the task rather than on review, deliberately: reaching
    review only *pauses* the session, and a paused session still owns the
    repo (SessionManager._repo_writers). A merge moves HEAD, so offering
    this beside Approve would be refused every single time. The lock is
    released when the task closes out and the session really stops —
    which is exactly when this becomes possible.
    """
    store = task_store()
    task, proj, repo, branch = _finishable(task_id, store, session_manager)

    base = proj.default_branch or "main"
    result = await merge_branch_async(repo, branch, base)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.failed_reason)

    task.merged_into = base
    store.update(task)
    store.log_progress(task.id, ProgressEntry(
        status=task.status, entry=f"Merged {branch} into {base}.", caller="human",
    ))
    # Best-effort: the work is safely in `base`, so failing to tidy the
    # branch isn't worth failing the request over.
    delete_branch_force(repo, branch, base)

    return {
        "status": "merged",
        "branch": branch,
        "into": base,
        "commits": result.commits,
        # A local merge leaves `base` ahead only locally — nothing pushes
        # it. Saying so is what stops "merged" being read as "in the
        # remote mainline". -1 means there is no remote to compare to.
        "base_ahead_of_remote": ahead_of_remote(repo, base),
    }


async def _open_task_pull_request(task_id: str, session_manager: SessionManager) -> dict:
    """Push the task's branch and open a PR for it via the `gh` CLI."""
    store = task_store()
    task, proj, repo, branch = _finishable(task_id, store, session_manager)

    pushed = await push_branch_async(repo, branch)
    if not pushed.ok:
        raise HTTPException(status_code=400, detail=f"Push failed: {pushed.failed_reason}")

    result = await open_pr_async(
        repo, branch, proj.default_branch or "main",
        title=task.title, body=task.description,
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.failed_reason)

    task.pull_request_url = result.url
    store.update(task)
    store.log_progress(task.id, ProgressEntry(
        status=task.status,
        entry=f"Opened pull request for {branch}: {result.url}",
        caller="human",
    ))
    return {"status": "opened", "branch": branch, "url": result.url}


async def finish_task_branch(
    task_id: str, action: str, session_manager: SessionManager,
) -> dict:
    """Finish a task's branch by the workspace's configured action.

    Used by the automatic on-approve path, which must never fail the
    approval: the task is legitimately done whether or not its branch
    could be merged, and leaving it stuck in review because of a
    conflict would be the worse outcome. So an HTTPException from the
    shared handlers is reported here rather than propagated.
    """
    try:
        if action == "merge":
            return await _merge_task_branch(task_id, session_manager)
        if action == "pull_request":
            return await _open_task_pull_request(task_id, session_manager)
        return {"status": "skipped", "reason": f"unknown finish action {action!r}"}
    except HTTPException as e:
        return {"status": "failed", "error": str(e.detail)}


def create_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tasks")
    async def list_tasks(
        status: str = Query(""),
        project: str = Query(""),
        limit: int = Query(0),
    ):
        """List tasks with optional filters.

        The agent_name/agent_running/agent_error fields join against the
        live sessions so a board card can show the same green/amber/red
        status dot as Task Detail without a second fetch per task. Only
        the writer (non-advisory) session is considered — advisory agents
        are observers and don't represent the task's active state.
        """
        store = task_store()
        tasks = store.list(status=status, project=project, limit=limit)
        # Index live sessions by task_id once rather than scanning the
        # full active list inside the per-task loop below.
        writers_by_task: dict[str, object] = {}
        for s in session_manager.active:
            if s.task_id and not s.advisory:
                writers_by_task[s.task_id] = s

        def _summary(t):
            w = writers_by_task.get(t.id)
            return {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "priority": t.priority.value,
                "tags": t.tags,
                "project": t.project,
                "assigned_to": t.assigned_to,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
                "progress_count": len(t.progress),
                "steps_count": len(t.steps),
                "steps_done": sum(1 for s in t.steps if s.status.value == "done"),
                "criteria_count": len(t.acceptance_criteria),
                "blocked_by_deps": len(store.unmet_dependencies(t)) > 0,
                "agent_name": w.name if w else "",
                "agent_running": bool(w and w.running),
                "agent_error": (w._last_error if w else ""),
            }

        return {"tasks": [_summary(t) for t in tasks]}

    @router.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        """Get full task details, plus what's left to do with its branch."""
        store = task_store()
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            **_task_to_response(task, store),
            "finish": task_finish_state(task, session_manager),
        }

    @router.get("/api/tasks/{task_id}/agents")
    async def list_task_agents(task_id: str):
        """All active sessions working this task — the writer plus any
        advisory agents (see Session.advisory), for the Task Detail
        screen's multi-agent view. task.assigned_to alone only ever
        names the writer, since advisory sessions never claim it."""
        from agent_knots.cockpit.web.routes.agents import _agent_to_response

        sessions = [s for s in session_manager.active if s.task_id == task_id]
        return {"agents": [_agent_to_response(s) for s in sessions]}

    @router.get("/api/tasks/{task_id}/history")
    async def list_task_session_history(task_id: str):
        """Past (stopped) sessions that worked this task, most recent
        first — Task Detail's "reopen and see what it did" links, since
        list_task_agents above only ever shows currently-active ones.
        Sessions aren't persisted beyond the wastebin, so this is the
        only place a finished session's existence survives at all."""
        from agent_knots.config import wastebin_dir
        from agent_knots.wastebin import WastebinStore

        entries = [e for e in WastebinStore(wastebin_dir()).list() if e.task_id == task_id]
        return {
            "sessions": [
                {
                    "id": e.session_id,
                    "name": e.name,
                    "role": e.role,
                    "advisory": e.advisory,
                    "model": e.model,
                    "tokens_used": e.tokens_used,
                    "cost_usd": e.cost_usd,
                    "started_at": e.started_at,
                    "stopped_at": e.stopped_at,
                }
                for e in entries
            ]
        }

    @router.post("/api/tasks")
    async def create_task(body: CreateTaskRequest):
        """Create a new task."""
        store = task_store()
        task = Task(
            id=new_task_id(body.project),
            title=body.title,
            description=body.description,
            priority=Priority(body.priority),
            status=TaskStatus(body.status) if body.status else TaskStatus.DRAFT,
            project=body.project,
            tags=body.tags,
            acceptance_criteria=body.acceptance_criteria,
            review_gate=ReviewGate(body.review_gate),
            dependencies=body.dependencies,
        )
        store.create(task)
        return _task_to_response(task, store)

    async def _maybe_pause_or_stop_finished_sessions(new_status: str, task: Task) -> None:
        """Runs before _maybe_fire_role_triggers, not after — a
        transition into review that also fires a new advisory reviewer
        must pause the *old* writer first, without racing the reviewer
        session that's about to be created (it doesn't exist yet at
        this point, since role triggers haven't fired).

        Shared with the agent-tool status-change path — see
        task/lifecycle.py and task/tools.py's
        make_session_aware_task_tools.
        """
        await maybe_pause_or_stop_finished_sessions(session_manager, new_status, task)

    def _maybe_fire_role_triggers(old_status: str, new_status: str, task: Task) -> None:
        """Shared with the agent-tool status-change path — see
        task/lifecycle.py and task/tools.py's
        make_session_aware_task_tools."""
        maybe_fire_role_triggers(session_manager, old_status, new_status, task)

    @router.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, body: UpdateTaskRequest):
        """Update a task's status, priority, assignment, or content fields.

        Criteria/steps are matched against existing entries by text so
        criteria_met / step status survive an edit that doesn't touch
        them — a blind overwrite would silently reset that state.

        Mutates the in-memory task across all the content-field checks
        below and writes once at the end, rather than a separate
        store.update() per field (a PATCH touching several fields used
        to do several redundant full-file disk writes and bump
        updated_at repeatedly instead of once). status and assign are
        each still their own store call — both TaskStore.set_status()
        and .assign() re-fetch the task from disk themselves, so unlike
        the plain content fields they can't just be batched into the
        in-memory object. status runs first and assign runs last so
        each sees whatever the other steps have already persisted.
        """
        store = task_store()
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        old_status = task.status.value
        if body.status:
            try:
                task = store.set_status(task_id, TaskStatus(body.status), actor="human")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            await _maybe_pause_or_stop_finished_sessions(task.status.value, task)
            _maybe_fire_role_triggers(old_status, task.status.value, task)

        dirty = False
        if body.priority:
            task.priority = Priority(body.priority)
            dirty = True
        if body.title:
            task.title = body.title
            dirty = True
        if body.description is not None:
            task.description = body.description
            dirty = True
        if body.tags is not None:
            task.tags = body.tags
            dirty = True
        if body.review_gate is not None:
            task.review_gate = ReviewGate(body.review_gate)
            dirty = True
        if body.dependencies is not None:
            task.dependencies = [d for d in body.dependencies if d != task_id]
            dirty = True
        if body.acceptance_criteria is not None:
            # criteria_met is keyed by criterion text, so preserving it
            # here is automatic — no matching needed, just don't touch it.
            task.acceptance_criteria = body.acceptance_criteria
            task.criteria_met = [c for c in task.criteria_met if c in body.acceptance_criteria]
            dirty = True
        if body.steps is not None:
            existing_by_title = {s.title: s for s in task.steps}
            new_steps = []
            for title in body.steps:
                existing = existing_by_title.get(title)
                if existing is not None:
                    new_steps.append(existing)
                else:
                    new_steps.append(Step(id=f"s-{secrets.token_hex(3)}", title=title))
            task.steps = new_steps
            dirty = True
        if dirty:
            task = store.update(task)

        if body.assign is not None:
            task = store.assign(task_id, body.assign)

        return _task_to_response(task, store)

    @router.post("/api/tasks/{task_id}/criteria/toggle")
    @raises_as(404)
    async def toggle_criterion(task_id: str, body: ToggleCriterionRequest):
        """Mark/unmark a single acceptance criterion as met."""
        store = task_store()
        if body.met:
            task = store.mark_criterion_met(task_id, body.criterion)
        else:
            task = store.unmark_criterion_met(task_id, body.criterion)
        return _task_to_response(task, store)

    @router.post("/api/tasks/draft")
    async def draft_task(body: DraftTaskRequest):
        """Draft a task's description/criteria/tags/steps from a title
        via a single non-tool-calling completion. Used by the "✨ Draft
        with agent" button in the create/edit dialog — no Strands Agent
        or session lifecycle involved, just one structured completion."""
        provider = provider_module.resolve_provider()
        if not provider.is_configured:
            raise HTTPException(status_code=400, detail="Settings not configured. Run setup first.")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url or None)
        prompt = (
            "Given a task title, draft a JSON object with fields: "
            "description (string), acceptance_criteria (list of strings), "
            "tags (list of strings), steps (list of strings). "
            "Respond with ONLY the raw JSON object — no markdown code fences, "
            "no commentary before or after it, no <think> reasoning block, "
            "no explanation of your reasoning at all — the very first "
            "character of your response must be '{'.\n\n"
            f"Title: {body.title}"
        )
        try:
            # No response_format — it's an OpenAI-specific strict-JSON-mode
            # parameter that not every OpenAI-*compatible* provider (e.g.
            # MiniMax) actually implements, and this app always goes
            # through OpenAIModel/AsyncOpenAI regardless of provider (see
            # provider.py). Passing an unsupported param 400s the whole
            # request instead of just getting a slightly less strict
            # completion, so ask for raw JSON in the prompt instead and
            # parse leniently below.
            resp = await client.chat.completions.create(
                model=provider.model,
                messages=[{"role": "user", "content": prompt}],
            )
            draft = _extract_json_object(resp.choices[0].message.content or "")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Draft generation failed: {e}")

        return {
            "description": draft.get("description", ""),
            "acceptance_criteria": draft.get("acceptance_criteria", []),
            "tags": draft.get("tags", []),
            "steps": draft.get("steps", []),
        }

    @router.post("/api/tasks/{task_id}/merge")
    async def merge_task(task_id: str):
        """Merge a finished task's branch into the workspace's base branch."""
        return await _merge_task_branch(task_id, session_manager)

    @router.post("/api/tasks/{task_id}/pull-request")
    async def open_task_pull_request(task_id: str):
        """Push the task's branch and open a pull request for it."""
        return await _open_task_pull_request(task_id, session_manager)

    @router.delete("/api/tasks/{task_id}")
    @raises_as(404)
    async def delete_task(task_id: str):
        """Delete a task."""
        store = task_store()
        store.delete(task_id)
        return {"status": "ok"}

    return router
