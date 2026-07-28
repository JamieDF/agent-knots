"""Task CRUD routes, including status/assign, criteria toggling, and
agent-assisted drafting. Also owns the role-trigger auto-start logic
that fires when a task's status transition crosses a workflow stage
boundary (Workflows screen)."""

import secrets

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.jsonutil import _extract_json_object
from agent_knots.cockpit.web.models import (
    CreateTaskRequest, DraftTaskRequest, ToggleCriterionRequest, UpdateTaskRequest,
)
from agent_knots.config import tasks_dir
from agent_knots import provider as provider_module
from agent_knots.session.manager import SessionManager
from agent_knots.task.lifecycle import maybe_auto_stop_finished_sessions, maybe_fire_role_triggers
from agent_knots.task.models import Priority, ReviewGate, Step, Task, TaskStatus, new_task_id
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


def create_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tasks")
    async def list_tasks(
        status: str = Query(""),
        project: str = Query(""),
        limit: int = Query(0),
    ):
        """List tasks with optional filters."""
        store = TaskStore(tasks_dir())
        tasks = store.list(status=status, project=project, limit=limit)
        return {
            "tasks": [
                {
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
                    "criteria_count": len(t.acceptance_criteria),
                    "blocked_by_deps": len(store.unmet_dependencies(t)) > 0,
                }
                for t in tasks
            ]
        }

    @router.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        """Get full task details."""
        store = TaskStore(tasks_dir())
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return _task_to_response(task, store)

    @router.get("/api/tasks/{task_id}/agents")
    async def list_task_agents(task_id: str):
        """All active sessions working this task — the writer plus any
        advisory agents (see Session.advisory), for the Task Detail
        screen's multi-agent view. task.assigned_to alone only ever
        names the writer, since advisory sessions never claim it."""
        from agent_knots.cockpit.web.routes.agents import _agent_to_response

        sessions = [s for s in session_manager.active if s.task_id == task_id]
        return {"agents": [_agent_to_response(s) for s in sessions]}

    @router.post("/api/tasks")
    async def create_task(body: CreateTaskRequest):
        """Create a new task."""
        store = TaskStore(tasks_dir())
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

    async def _maybe_auto_stop_finished_sessions(new_status: str, task: Task) -> None:
        """Runs before _maybe_fire_role_triggers, not after — a
        transition into review that also fires a new advisory reviewer
        must stop the *old* writer first, without racing the reviewer
        session that's about to be created (it doesn't exist yet at
        this point, since role triggers haven't fired).

        Shared with the agent-tool status-change path — see
        task/lifecycle.py and task/tools.py's
        make_session_aware_status_tools.
        """
        await maybe_auto_stop_finished_sessions(session_manager, new_status, task)

    def _maybe_fire_role_triggers(old_status: str, new_status: str, task: Task) -> None:
        """Shared with the agent-tool status-change path — see
        task/lifecycle.py and task/tools.py's
        make_session_aware_status_tools."""
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
        store = TaskStore(tasks_dir())
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        old_status = task.status.value
        if body.status:
            try:
                task = store.set_status(task_id, TaskStatus(body.status), actor="human")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            await _maybe_auto_stop_finished_sessions(task.status.value, task)
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
        store = TaskStore(tasks_dir())
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

    @router.delete("/api/tasks/{task_id}")
    @raises_as(404)
    async def delete_task(task_id: str):
        """Delete a task."""
        store = TaskStore(tasks_dir())
        store.delete(task_id)
        return {"status": "ok"}

    return router
