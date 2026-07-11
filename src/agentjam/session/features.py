"""Advanced session features — memory, multi-agent, checkpoint, steering.

All features are wired via hooks, interventions, and system prompt
enhancements — no changes to the core session manager needed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from strands.hooks.events import AfterToolCallEvent
from strands.tools import tool as _tool_dec

from agentjam.config import sessions_dir as _sessions_dir
from agentjam.config import tasks_dir as _tasks_dir


# ── Memory: cross-session context via progress injection ────────────────────


def inject_memory(task_id: str) -> str:
    """Build a memory block from the task's progress log.

    Includes recent entries so a new session picking up the task knows
    what happened before. This is appended to the system prompt.
    """
    from agentjam.task.store import TaskStore

    store = TaskStore(_tasks_dir())
    task = store.get(task_id)
    if not task or not task.progress:
        return ""

    recent = task.progress[-10:]  # Last 10 entries.
    lines = ["## Previous Session Context", ""]
    lines.append(f"The following work was done in previous sessions on task {task_id}:")
    lines.append("")
    for p in recent:
        ts = time.strftime("%H:%M", time.localtime(p.timestamp))
        lines.append(f"- [{ts}] [{p.status.value}] {p.entry}")
        if p.next_step:
            lines.append(f"  Next: {p.next_step}")
    lines.append("")
    lines.append("Continue from where the previous session left off.")
    lines.append("Use log_progress to record your own progress.")

    return "\n".join(lines)


# ── Multi-agent: sub-agent delegation ────────────────────────────────────────


def make_delegate_tool(session_manager: Any) -> Any:
    """Create a tool that lets an agent delegate work to a sub-agent.

    The sub-agent gets its own session and task. The parent can check
    results via read_task.
    """

    @_tool_dec(description="Delegate a sub-task to another agent. Creates a new session to work on it.")
    def delegate_task(
        title: str,
        description: str = "",
        acceptance_criteria: list[str] | None = None,
    ) -> dict:
        """Create a sub-task and start an agent on it.

        Args:
            title: Short title for the sub-task.
            description: Details about what needs to be done.
            acceptance_criteria: List of verifiable conditions.

        Returns:
            The created sub-task and session IDs.
        """
        from agentjam.task.store import TaskStore
        from agentjam.task.models import Task, TaskStatus, new_task_id

        store = TaskStore(_tasks_dir())
        task = store.create(Task(
            id=new_task_id(),
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria or [],
            status=TaskStatus.IN_PROGRESS,
        ))

        # Start a session on this sub-task asynchronously.
        import asyncio
        asyncio.create_task(
            session_manager.start(
                mode="agent",
                task_id=task.id,
                task_description=description or title,
            )
        )

        return {
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value,
            "message": "Sub-agent started. Monitor progress via read_task.",
        }

    return delegate_task


# ── Checkpoint: session state save/load ──────────────────────────────────────


def save_checkpoint(session_id: str, session_data: dict) -> None:
    """Save session state to a YAML checkpoint file."""
    import yaml

    path = Path(_sessions_dir()) / f"{session_id}.checkpoint.yaml"
    data = {
        "session_id": session_id,
        "timestamp": time.time(),
        **session_data,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(data, default_flow_style=False))
    tmp.rename(path)


def load_checkpoint(session_id: str) -> dict | None:
    """Load a session checkpoint, or None if not found."""
    import yaml

    path = Path(_sessions_dir()) / f"{session_id}.checkpoint.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return None


# ── Steering: criteria validation via hooks ──────────────────────────────────


def register_steering_hook(agent: Any, task_id: str) -> None:
    """Register a hook that validates tool outputs against acceptance criteria.

    When a tool finishes, checks if the output satisfies any pending
    acceptance criteria. If it does, auto-marks them as met.
    """
    from agentjam.task.store import TaskStore
    from agentjam.task.models import TaskStatus

    def on_tool(event: AfterToolCallEvent) -> None:
        if not task_id:
            return

        store = TaskStore(_tasks_dir())
        task = store.get(task_id)
        if not task or task.status.is_terminal():
            return

        tool_output = ""
        if hasattr(event, "result") and event.result:
            tool_output = str(event.result).lower()
        elif hasattr(event, "exception") and event.exception:
            return  # Tool failed — don't check criteria.

        # Check each pending criterion against the tool output.
        for i, criterion in enumerate(task.acceptance_criteria):
            # Simple keyword match — production would use LLM evaluation.
            keywords = criterion.lower().split()
            matches = all(kw in tool_output for kw in keywords if len(kw) > 3)
            if matches:
                from agentjam.task.models import ProgressEntry
                entry = ProgressEntry(
                    entry=f"✓ Criterion met: {criterion}",
                    status=task.status,
                    caller=f"agent:steering",
                )
                store.log_progress(task_id, entry)
                break  # One criterion per tool call.

    agent.add_hook(on_tool, AfterToolCallEvent)


# ── Structured output: task data validation ──────────────────────────────────


def validate_task_output(data: dict) -> dict:
    """Validate task creation/update data against the task model.

    Used before creating or updating tasks to ensure well-formed data.
    """
    from agentjam.task.models import TaskStatus, Priority

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
