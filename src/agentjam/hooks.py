"""Session hooks for cost tracking and auto progress logging.

Registered on every agent session to:
1. Track real token usage from model calls (replaces hardcoded estimate)
2. Auto-log task progress when the agent uses tools
"""

from __future__ import annotations

import time

from strands.hooks.events import AfterModelCallEvent, AfterToolCallEvent


def register_session_hooks(agent, session: "Session") -> None:
    """Register hooks on an agent for a session.

    Args:
        agent: The Strands Agent instance.
        session: The agent-jam Session being observed.
    """
    # ── cost tracking ──────────────────────────────────────────────────
    def on_model_call(event: AfterModelCallEvent) -> None:
        """Track token usage from each model call."""
        if event.stop_response:
            # Usage is nested in message.metadata.usage on ModelStopResponse.
            msg = getattr(event.stop_response, "message", None)
            if msg and isinstance(msg, dict):
                meta = msg.get("metadata", {})
                usage = meta.get("usage", {})
                if usage:
                    session.tokens_used += usage.get("inputTokens", 0) or 0
                    session.tokens_used += usage.get("outputTokens", 0) or 0
                    # Rough cost: $0.30/1M tokens for MiniMax M2.7.
                    session.cost_usd = session.tokens_used * 0.0000003

    agent.add_hook(on_model_call, AfterModelCallEvent)

    # ── auto progress logging ──────────────────────────────────────────
    def on_tool_call(event: AfterToolCallEvent) -> None:
        """Auto-log task progress when the agent uses tools."""
        task_id = session.task_id
        if not task_id or not event.tool_use:
            return

        tool_name = (event.selected_tool.__name__
                     if event.selected_tool else "unknown")

        # Only log meaningful tools, not internal ones.
        if tool_name in ("log_progress", "read_task", "list_tasks"):
            return

        args = event.tool_use.input if hasattr(event.tool_use, "input") else {}
        args_str = str(args)[:80] if args else ""

        try:
            from agentjam.task.store import TaskStore
            from agentjam.task.models import ProgressEntry, TaskStatus
            from agentjam.config import tasks_dir

            store = TaskStore(tasks_dir())
            task = store.get(task_id)
            if task and not task.status.is_terminal():
                entry = ProgressEntry(
                    entry=f"[{tool_name}] {args_str}".strip(),
                    status=task.status,
                    caller=f"agent:{session.id}",
                )
                store.log_progress(task_id, entry)
        except Exception:
            pass  # Don't break the agent for logging failures.

    agent.add_hook(on_tool_call, AfterToolCallEvent)
