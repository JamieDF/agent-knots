"""Task tools for Strands agents.

These functions are decorated as Strands tools so agents can create,
read, update, and log progress on tasks during a session.

Usage:
    from agentjam.task.tools import create_task, read_task, log_progress

    agent = Agent(tools=[create_task, read_task, log_progress, ...])
"""

from __future__ import annotations

from strands.tools import tool

from agentjam.config import tasks_dir
from agentjam.task.models import (
    Priority,
    ProgressEntry,
    Step,
    Task,
    TaskStatus,
    new_task_id,
)
from agentjam.task.store import TaskStore


def _store() -> TaskStore:
    return TaskStore(tasks_dir())


# ── task tools ───────────────────────────────────────────────────────────────


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
        The created task with its ID.
    """
    store = _store()
    task = Task(
        id=new_task_id(),
        title=title,
        description=description,
        priority=Priority(priority),
        acceptance_criteria=acceptance_criteria or [],
    )
    store.create(task)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
    }


@tool(description="Read full details of a task by its ID.")
def read_task(task_id: str) -> dict:
    """Read a task's details including steps, criteria, and progress.

    Args:
        task_id: The task ID (e.g. 'T-2026-07-07-...').

    Returns:
        Full task details, or an error if not found.
    """
    store = _store()
    task = store.get(task_id)
    if task is None:
        return {"error": f"Task {task_id!r} not found"}

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "acceptance_criteria": task.acceptance_criteria,
        "steps": [{"id": s.id, "title": s.title, "status": s.status.value} for s in task.steps],
        "progress_count": len(task.progress),
        "assigned_to": task.assigned_to,
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
    store = _store()
    tasks = store.list(status=status, limit=20)
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


@tool(description="Update a task's status. Use this to move tasks through the workflow.")
def update_task_status(task_id: str, status: str) -> dict:
    """Update a task's status.

    Args:
        task_id: The task ID.
        status: New status. One of 'draft', 'open', 'planned',
                'in_progress', 'blocked', 'review', 'done', 'abandoned'.

    Returns:
        Updated task details.
    """
    store = _store()
    task = store.set_status(task_id, TaskStatus(status))
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
    }


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
        Updated task details.
    """
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


@tool(description="Log progress on a task. Call this after every meaningful action so progress survives context loss.")
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
        Confirmation with updated progress count.
    """
    store = _store()
    pe = ProgressEntry(
        entry=entry,
        status=TaskStatus(status),
        next_step=next_step,
        resolution=resolution,
        caller="agent",
    )
    task = store.log_progress(task_id, pe)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "progress_entries": len(task.progress),
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


# Export list of all task tools for easy passing to Agent.
ALL_TASK_TOOLS = [
    create_task,
    read_task,
    list_tasks,
    update_task_status,
    update_task,
    log_progress,
    add_step,
]
