"""Task tools for Strands agents.

These functions are decorated as Strands tools so agents can create,
read, update, and log progress on tasks during a session.

Usage:
    from agent_knots.task.tools import create_task, read_task, log_progress

    agent = Agent(tools=[create_task, read_task, log_progress, ...])
"""

from __future__ import annotations

import asyncio
from typing import Any

from strands.tools import tool

from agent_knots.config import tasks_dir
from agent_knots.task.models import (
    Priority,
    ProgressEntry,
    Step,
    Task,
    TaskStatus,
    new_task_id,
)
from agent_knots.task.store import TaskStore


def _store() -> TaskStore:
    return TaskStore(tasks_dir())


def validate_task_output(data: dict) -> dict:
    """Validate task creation/update fields before they hit the store.

    Without this, an invalid priority/status raises an uncaught ValueError
    from inside Priority(...)/TaskStatus(...) — this turns that into a
    structured, tool-callable error instead.
    """
    errors = []

    if "title" in data and (not data["title"] or not isinstance(data["title"], str)):
        errors.append("title must be a non-empty string")

    if "status" in data:
        try:
            TaskStatus(data["status"])
        except ValueError:
            errors.append(f"invalid status: {data['status']}")

    if "priority" in data:
        try:
            Priority(data["priority"])
        except ValueError:
            errors.append(f"invalid priority: {data['priority']}")

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True, "data": data}


# ── task tools ───────────────────────────────────────────────────────────────


def _create_task_impl(
    title: str,
    description: str,
    priority: str,
    acceptance_criteria: list[str] | None,
    project: str,
) -> dict:
    validation = validate_task_output({"title": title, "priority": priority})
    if not validation["valid"]:
        return {"error": "; ".join(validation["errors"])}

    store = _store()
    task = Task(
        id=new_task_id(project),
        title=title,
        description=description,
        priority=Priority(priority),
        acceptance_criteria=acceptance_criteria or [],
        project=project,
    )
    store.create(task)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
        "project": task.project,
    }


@tool(description="Create a new task in the project tracker. Use this to record work that needs to be done.")
def create_task(
    title: str,
    description: str = "",
    priority: str = "medium",
    acceptance_criteria: list[str] | None = None,
) -> dict:
    """Create a new task.

    Args:
        title: Short summary of what needs to be done.
        description: Longer context about the task.
        priority: One of 'low', 'medium', 'high', 'urgent'.
        acceptance_criteria: List of verifiable conditions for completion.

    Returns:
        The created task with its ID, or an error if title/priority are
        invalid.
    """
    return _create_task_impl(title, description, priority, acceptance_criteria, project="")


def _read_task_impl(task_id: str, project: str) -> dict:
    store = _store()
    task = store.get(task_id)
    if task is None or (project and task.project != project):
        # Same "not found" for missing vs. wrong-workspace — a
        # workspace-scoped session shouldn't be able to confirm a task
        # even exists in a workspace it isn't allowed to see into.
        return {"error": f"Task {task_id!r} not found"}

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "acceptance_criteria": task.acceptance_criteria,
        "criteria_met": task.criteria_met,
        "unmet_criteria": task.unmet_criteria(),
        "steps": [{"id": s.id, "title": s.title, "status": s.status.value} for s in task.steps],
        "progress_count": len(task.progress),
        "assigned_to": task.assigned_to,
    }


@tool(description="Read full details of a task by its ID.")
def read_task(task_id: str) -> dict:
    """Read a task's details including steps, criteria, and progress.

    Args:
        task_id: The task ID (e.g. 'T-2026-07-07-...').

    Returns:
        Full task details, or an error if not found.
    """
    return _read_task_impl(task_id, project="")


def _list_tasks_impl(status: str, project: str) -> dict:
    store = _store()
    tasks = store.list(status=status, project=project, limit=20)
    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "priority": t.priority.value,
                "progress_count": len(t.progress),
            }
            for t in tasks
        ]
    }


@tool(description="List tasks, optionally filtered by status. Use this to see what work is pending.")
def list_tasks(status: str = "") -> dict:
    """List all tasks, optionally filtered by status.

    Args:
        status: Optional filter. One of 'draft', 'open', 'planned',
                'in_progress', 'blocked', 'review', 'done', 'abandoned'.
                Omit for all tasks.

    Returns:
        List of task summaries.
    """
    return _list_tasks_impl(status, project="")


_UPDATE_STATUS_DESCRIPTION = (
    "Update a task's status. Use this to move tasks through the workflow. Moving to 'done' "
    "requires every acceptance criterion to already be marked met via mark_criterion_met, AND "
    "(unless the task's review_gate is 'none') the task must already be in 'review' status — go "
    "in_progress -> review -> done, not straight to done. Even from 'review', you (the agent) "
    "cannot complete the done transition yourself when review_gate isn't 'none' — that requires "
    "a human to actually review and close it out. Move the task to 'review' and stop there; a "
    "human (or a separate reviewer session) finishes it."
)


def _update_task_status_impl(task_id: str, status: str) -> dict:
    validation = validate_task_output({"status": status})
    if not validation["valid"]:
        return {"error": "; ".join(validation["errors"])}

    store = _store()
    try:
        task = store.set_status(task_id, TaskStatus(status))
    except ValueError as e:
        return {"error": str(e)}
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
    }


@tool(description=_UPDATE_STATUS_DESCRIPTION)
def update_task_status(task_id: str, status: str) -> dict:
    """Update a task's status.

    Args:
        task_id: The task ID.
        status: New status. One of 'draft', 'open', 'planned',
                'in_progress', 'blocked', 'review', 'done', 'abandoned'.

    Returns:
        Updated task details, or an error if the status is malformed or
        the transition isn't allowed (e.g. unmet acceptance criteria for
        'done').
    """
    return _update_task_status_impl(task_id, status)


@tool(description="Update a task's details — title, description, priority, or acceptance criteria. Only pass the fields you want to change.")
def update_task(
    task_id: str,
    title: str = "",
    description: str = "",
    priority: str = "",
    acceptance_criteria: list[str] | None = None,
) -> dict:
    """Update a task's metadata fields in place.

    Args:
        task_id: The task ID.
        title: New title (omit to keep current).
        description: New description (omit to keep current).
        priority: New priority (omit to keep current).
        acceptance_criteria: New acceptance criteria list (omit to keep current).

    Returns:
        Updated task details, or an error if title/priority are invalid.
    """
    to_check = {k: v for k, v in {"title": title, "priority": priority}.items() if v}
    validation = validate_task_output(to_check)
    if not validation["valid"]:
        return {"error": "; ".join(validation["errors"])}

    store = _store()
    task = store.get(task_id)
    if task is None:
        return {"error": f"Task {task_id!r} not found"}

    changed = False
    if title:
        task.title = title
        changed = True
    if description:
        task.description = description
        changed = True
    if priority:
        task.priority = Priority(priority)
        changed = True
    if acceptance_criteria is not None:
        task.acceptance_criteria = acceptance_criteria
        changed = True

    if changed:
        store.update(task)

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "acceptance_criteria": task.acceptance_criteria,
    }


_LOG_PROGRESS_DESCRIPTION = (
    "Log progress on a task. Call this after every meaningful action so progress survives "
    "context loss. The status field can also move the task forward, subject to the same rules "
    "as update_task_status (e.g. 'done' needs all acceptance criteria met, the task already in "
    "'review' unless review_gate is 'none', and even then a human — not you — has to be the one "
    "to actually complete the done transition when review_gate isn't 'none')."
)


def _log_progress_impl(
    task_id: str, entry: str, status: str = "in_progress",
    next_step: str = "", resolution: str = "",
) -> dict:
    validation = validate_task_output({"status": status})
    if not validation["valid"]:
        return {"error": "; ".join(validation["errors"])}

    store = _store()
    pe = ProgressEntry(
        entry=entry,
        status=TaskStatus(status),
        next_step=next_step,
        resolution=resolution,
        caller="agent",
    )
    try:
        task = store.log_progress(task_id, pe)
    except ValueError as e:
        return {"error": str(e)}
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "progress_entries": len(task.progress),
    }


@tool(description=_LOG_PROGRESS_DESCRIPTION)
def log_progress(
    task_id: str,
    entry: str,
    status: str = "in_progress",
    next_step: str = "",
    resolution: str = "",
) -> dict:
    """Record a progress entry on a task.

    Every meaningful action (file edited, test run, decision made) should
    be logged here. This is the recovery point — if context is lost,
    the next agent reads this log to resume.

    Args:
        task_id: The task ID to log progress against.
        entry: What you just did (e.g. 'Created auth module with login').
        status: The new task status (default 'in_progress').
        next_step: What you plan to do next.
        resolution: How a blocker was resolved (if applicable).

    Returns:
        Confirmation with updated progress count, or an error if the
        status is malformed or the status change isn't allowed (e.g.
        unmet acceptance criteria).
    """
    return _log_progress_impl(task_id, entry, status, next_step, resolution)


@tool(description="Mark one acceptance criterion of a task as satisfied. All criteria must be marked met before the task can be moved to 'done' — update_task_status/log_progress will refuse a 'done' transition otherwise. Only mark a criterion met once you've actually verified it (e.g. ran the test, confirmed the behavior) — don't mark it met just because you attempted it.")
def mark_criterion_met(task_id: str, criterion: str) -> dict:
    """Mark a single acceptance criterion as satisfied.

    Args:
        task_id: The task ID.
        criterion: The exact criterion text (must match one of the task's
            acceptance_criteria) that you've verified is now true.

    Returns:
        The task's current criteria status.
    """
    store = _store()
    try:
        task = store.mark_criterion_met(task_id, criterion)
    except ValueError as e:
        return {"error": str(e)}
    return {
        "id": task.id,
        "acceptance_criteria": task.acceptance_criteria,
        "criteria_met": task.criteria_met,
        "unmet_criteria": task.unmet_criteria(),
        "all_criteria_met": task.all_criteria_met(),
    }


@tool(description="Add a step to a task's plan. Use this to break work into smaller pieces.")
def add_step(task_id: str, step_title: str) -> dict:
    """Add a step to a task's plan.

    Args:
        task_id: The task ID.
        step_title: The step description (e.g. 'Add login form component').

    Returns:
        The added step details.
    """
    import secrets
    store = _store()
    step = Step(id=f"s-{secrets.token_hex(3)}", title=step_title)
    task = store.add_step(task_id, step)
    return {
        "id": task.id,
        "step_id": step.id,
        "step_title": step.title,
        "total_steps": len(task.steps),
    }


# ── session-aware task tools ────────────────────────────────────────────────
#
# update_task_status and log_progress above have no SessionManager
# reference and call TaskStore directly — an agent using them to move
# its own task into review/done/abandoned (the normal way an autonomous
# builder finishes) never triggered the same auto-stop / role-trigger
# side effects a human changing status through the web PATCH already
# gets. make_session_aware_task_tools produces session-bound versions
# that do, swapped in by SessionManager._build_tools the same way the
# sandboxed shell/editor tools are (see session/manager.py).


async def _deferred_status_side_effects(
    session_manager: Any, old_status: str, new_status: str, task_id: str,
) -> None:
    """Runs the same side effects the web PATCH route triggers — never
    awaited directly from the tool call that changed the status.

    That matters: the calling session can itself be among the ones
    maybe_pause_or_stop_finished_sessions acts on (an agent marking its
    own task review or done is the whole point of this). Both
    SessionManager.stop() and the pause path's interrupt() cancel
    session._task and await it — a task cannot cancel-and-await itself,
    so that call has to happen from a *different* asyncio Task than the
    one running the tool call. Scheduling this whole function (rather
    than awaiting it inline) is what provides that separation; the
    ordering inside it (pause/stop before firing new role-triggered
    sessions) is preserved exactly as the web route's version has it,
    since both steps run in this one task.
    """
    from agent_knots.task.lifecycle import (
        maybe_pause_or_stop_finished_sessions,
        maybe_fire_role_triggers,
    )

    store = _store()
    task = store.get(task_id)
    if task is None:
        return
    await maybe_pause_or_stop_finished_sessions(session_manager, new_status, task)
    maybe_fire_role_triggers(session_manager, old_status, new_status, task)


def _schedule_side_effects_if_status_changed(
    loop: asyncio.AbstractEventLoop, session_manager: Any, task_id: str,
    old_status: str, result: dict,
) -> None:
    """asyncio.create_task() would silently do nothing here — Strands
    runs synchronous tool functions (this one included) via
    asyncio.to_thread, so there is no running event loop in the thread
    this executes on, and create_task() needs one in the *current*
    thread. run_coroutine_threadsafe schedules onto `loop` (the main
    loop, captured back when this session started, on the thread that
    actually runs it) regardless of which thread calls it from — the
    only thing that reliably works whether Strands is executing this
    inline or off-thread, since we don't get to assume which. Confirmed
    live: create_task() here produced 'coroutine was never awaited'
    with no side effect ever running, silently.
    """
    new_status = result.get("status")
    if "error" in result or not new_status or new_status == old_status:
        return
    asyncio.run_coroutine_threadsafe(
        _deferred_status_side_effects(session_manager, old_status, new_status, task_id),
        loop,
    )


def make_session_aware_task_tools(session_manager: Any, session_id: str, project_id: str = "") -> list:
    """create_task, read_task, list_tasks, update_task_status, and
    log_progress, all bound to this specific session.

    Three things layered on top of the plain (module-level) versions:
      - workspace scoping: if project_id is set, create/read/list are
        confined to that workspace. project is deliberately not an
        agent-facing parameter on any of these (unlike title/status/
        etc.) — it's closed over instead, the same way review_gate
        approval is restricted to actor="human" in task/store.py: a
        value the caller must never be able to override by just asking.
      - auto-stop / role-trigger side effects on status changes — see
        the module note above.
      - task adoption: a session started with no task_id adopts the
        first task it creates or logs progress/status on, so the goal
        rail (and Task Detail's "who's working on this") reflect a
        task an agent picks up mid-session the same as one it was
        started with. Only the first touch counts — see
        SessionManager.maybe_adopt_task.

    Must be called from the session's own async start() (i.e. on the
    main event loop) so asyncio.get_running_loop() below captures the
    right loop — see _schedule_side_effects_if_status_changed.
    """
    loop = asyncio.get_running_loop()
    workspace_note = " The task is always created in this session's workspace." if project_id else ""
    workspace_visibility_note = " Only tasks in this session's workspace are visible." if project_id else ""

    @tool(description=f"Create a new task in the project tracker. Use this to record work that needs to be done.{workspace_note}")
    def create_task(
        title: str,
        description: str = "",
        priority: str = "medium",
        acceptance_criteria: list[str] | None = None,
    ) -> dict:
        """Create a new task.

        Args:
            title: Short summary of what needs to be done.
            description: Longer context about the task.
            priority: One of 'low', 'medium', 'high', 'urgent'.
            acceptance_criteria: List of verifiable conditions for completion.

        Returns:
            The created task with its ID, or an error if title/priority are
            invalid.
        """
        result = _create_task_impl(title, description, priority, acceptance_criteria, project=project_id)
        if "id" in result:
            session_manager.maybe_adopt_task(session_id, result["id"])
        return result

    @tool(description=f"Read full details of a task by its ID.{workspace_visibility_note}")
    def read_task(task_id: str) -> dict:
        """Read a task's details including steps, criteria, and progress.

        Args:
            task_id: The task ID (e.g. 'T-2026-07-07-...').

        Returns:
            Full task details, or an error if not found (including if the
            task exists but belongs to a different workspace).
        """
        return _read_task_impl(task_id, project=project_id)

    @tool(description=f"List tasks, optionally filtered by status. Use this to see what work is pending.{workspace_visibility_note}")
    def list_tasks(status: str = "") -> dict:
        """List tasks, optionally filtered by status.

        Args:
            status: Optional filter. One of 'draft', 'open', 'planned',
                    'in_progress', 'blocked', 'review', 'done', 'abandoned'.
                    Omit for all tasks.

        Returns:
            List of task summaries.
        """
        return _list_tasks_impl(status, project=project_id)

    @tool(description=_UPDATE_STATUS_DESCRIPTION)
    def update_task_status(task_id: str, status: str) -> dict:
        before = _store().get(task_id)
        old_status = before.status.value if before else ""
        result = _update_task_status_impl(task_id, status)
        _schedule_side_effects_if_status_changed(loop, session_manager, task_id, old_status, result)
        if "error" not in result:
            session_manager.maybe_adopt_task(session_id, task_id)
        return result

    @tool(description=_LOG_PROGRESS_DESCRIPTION)
    def log_progress(
        task_id: str, entry: str, status: str = "in_progress",
        next_step: str = "", resolution: str = "",
    ) -> dict:
        before = _store().get(task_id)
        old_status = before.status.value if before else ""
        result = _log_progress_impl(task_id, entry, status, next_step, resolution)
        _schedule_side_effects_if_status_changed(loop, session_manager, task_id, old_status, result)
        if "error" not in result:
            session_manager.maybe_adopt_task(session_id, task_id)
        return result

    return [create_task, read_task, list_tasks, update_task_status, log_progress]


# Export list of all task tools for easy passing to Agent.
ALL_TASK_TOOLS = [
    create_task,
    read_task,
    list_tasks,
    update_task_status,
    update_task,
    log_progress,
    add_step,
    mark_criterion_met,
]
