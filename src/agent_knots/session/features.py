"""Advanced session features — memory, multi-agent delegation, steering.

All features are wired via hooks, interventions, and system prompt
enhancements — no changes to the core session manager needed.
"""

from __future__ import annotations

import time
from typing import Any

from strands.hooks.events import AfterToolCallEvent
from strands.tools import tool as _tool_dec

from agent_knots.storage import task_store
from agent_knots.events import Event, EventType


# ── Memory: cross-session context via progress injection ────────────────────


def inject_memory(task_id: str) -> str:
    """Build a memory block from the task's progress log.

    Includes recent entries so a new session picking up the task knows
    what happened before. This is appended to the system prompt.
    """
    store = task_store()
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


def make_delegate_tool(session_manager: Any, parent_session_id: str) -> Any:
    """Create a tool that lets an agent delegate work to a sub-agent.

    The sub-agent gets its own session and task. The parent can check
    results via read_task. Delegation is task-mediated, not
    session-parented — there's no session hierarchy or direct
    session-to-session messaging, just a shared Task record. The
    Atelier UI's delegation card expands by opening its own SSE
    subscription to the sub-session, not by nesting the child's events
    inside the parent's stream.
    """
    # Captured here, not inside delegate_task below: this factory runs
    # on the main event loop (called synchronously from within the
    # parent session's own async start()), but delegate_task itself
    # gets called later by Strands via asyncio.to_thread — a worker
    # thread with no running loop of its own. asyncio.create_task()
    # from in there silently does nothing (confirmed live: "coroutine
    # was never awaited", no sub-session ever created).
    # run_coroutine_threadsafe(coro, loop) is what actually schedules
    # onto the right loop regardless of which thread calls it from.
    import asyncio
    loop = asyncio.get_running_loop()

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
        from agent_knots.task.models import Task, TaskStatus, new_task_id

        store = task_store()
        task = store.create(Task(
            id=new_task_id(),
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria or [],
            status=TaskStatus.IN_PROGRESS,
        ))

        # Start a session on this sub-task asynchronously.

        async def _start_and_link() -> None:
            sub_session = await session_manager.start(
                mode="agent",
                task_id=task.id,
                task_description=description or title,
            )
            parent = session_manager.get(parent_session_id)
            if parent is not None:
                parent._broadcast(Event(
                    type=EventType.DELEGATE,
                    session_id=parent_session_id,
                    message=title,
                    data={
                        "sub_session_id": sub_session.id,
                        "sub_task_id": task.id,
                        "title": title,
                    },
                ))

        asyncio.run_coroutine_threadsafe(_start_and_link(), loop)

        return {
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value,
            "message": "Sub-agent started. Monitor progress via read_task.",
        }

    return delegate_task


# ── Ask User: blocking prompt for human decisions ──────────────────────────


def make_ask_user_tool(session_manager: Any, session_id: str) -> Any:
    """Create a tool that lets the agent ask the user a question mid-task.

    The tool blocks until the user answers via the web UI (the blocker
    event's answer bar) or API. While blocked, the agent's turn is paused
    — the event loop remains free to handle the answer endpoint. When the
    user answers, the tool returns the answer and the agent resumes in the
    same turn.

    Uses threading.Event (not asyncio.Event) because the @tool decorator
    runs synchronous tool functions in asyncio.to_thread — the tool thread
    blocks on the event, while the main event loop stays responsive.
    """

    import threading

    @_tool_dec(description="Ask the user a question and wait for their answer. Use when you need a decision, clarification, or preference before continuing.")
    def ask_user(
        question: str,
        options: list[str] | None = None,
    ) -> dict:
        """Pause and ask the user a question.

        Args:
            question: The question to ask. Be specific about what you need.
            options: Optional list of choices to offer as quick-select buttons.

        Returns:
            The user's answer.
        """
        parent = session_manager.get(session_id)
        if parent is None:
            return {"error": "Session not found"}

        # Broadcast the blocker event to all subscribers before blocking.
        parent._broadcast(Event(
            type=EventType.BLOCKER,
            session_id=session_id,
            message=question,
            data={"options": options} if options else None,
        ))

        # Block until the user answers.
        event = threading.Event()
        parent._pending_question = {
            "event": event,
            "answer": None,
            "question": question,
            "options": options,
        }

        event.wait()

        # Retrieve and clear the answer.
        pending = parent._pending_question
        answer = (pending or {}).get("answer", "") if pending else ""
        parent._pending_question = None

        return {
            "question": question,
            "answer": answer,
        }

    return ask_user


def register_steering_hook(agent: Any, task_id: str, session: Any = None) -> None:
    """Register a hook that nudges the agent toward marking criteria met.

    When a tool finishes, checks if the output looks like it satisfies a
    pending (not-yet-met) acceptance criterion. This is advisory only — a
    simple keyword match, not real verification — so it logs a suggestion
    rather than calling mark_criterion_met itself. The actual DONE gate
    (TaskStore._validate_transition) only respects explicit
    mark_criterion_met calls, precisely so a keyword match can't quietly
    satisfy real enforcement. Production would want LLM-based evaluation
    here instead of keyword matching.
    """
    def on_tool(event: AfterToolCallEvent) -> None:
        if not task_id:
            return

        store = task_store()
        task = store.get(task_id)
        if not task or task.status.is_terminal():
            return

        tool_output = ""
        if hasattr(event, "result") and event.result:
            tool_output = str(event.result).lower()
        elif hasattr(event, "exception") and event.exception:
            return  # Tool failed — don't check criteria.

        # Check each pending (not-yet-met) criterion against the tool output.
        for criterion in task.unmet_criteria():
            # Simple keyword match — production would use LLM evaluation.
            keywords = criterion.lower().split()
            matches = all(kw in tool_output for kw in keywords if len(kw) > 3)
            if matches:
                from agent_knots.task.models import ProgressEntry
                nudge = (
                    f"Possible match for criterion {criterion!r} — "
                    "verify and call mark_criterion_met if confirmed."
                )
                entry = ProgressEntry(
                    entry=nudge,
                    status=task.status,
                    caller="agent:steering",
                )
                store.log_progress(task_id, entry)
                if session is not None:
                    session._broadcast(Event(
                        type=EventType.STEER,
                        session_id=session.id,
                        message=nudge,
                    ))
                break  # One suggestion per tool call.

    agent.add_hook(on_tool, AfterToolCallEvent)
