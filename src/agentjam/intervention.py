"""Mode-aware intervention handler for assume/relinquish.

When the user assumes control (assistant mode), tool calls are cancelled
so the agent cannot execute tools autonomously. When relinquishing
(agent mode), tools execute freely.

Future: use Confirm to prompt the user for each tool call in assistant mode.
"""

from __future__ import annotations

from strands.hooks.events import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
)
from strands.interventions import InterventionHandler
from strands.interventions.actions import Deny, Proceed


class ModeInterventionHandler(InterventionHandler):
    """Intervention handler that gates tool execution based on session mode.

    - agent mode: Proceed — tools execute autonomously
    - assistant mode: Deny — tools are blocked, agent must ask user
    - reviewer/security mode: Deny — read-only, no tool execution
    """

    def __init__(self, get_mode: callable) -> None:
        super().__init__()
        self._get_mode = get_mode

    @property
    def name(self) -> str:
        return "mode-intervention"

    def _is_restricted(self) -> bool:
        """Return True if tool execution should be blocked."""
        mode = self._get_mode()
        return mode in ("assistant", "reviewer", "security")

    def on_before_tool_call(self, event: BeforeToolCallEvent):
        if self._is_restricted():
            tool_name = event.selected_tool.__name__ if event.selected_tool else "unknown"
            return Deny(reason=f"User is driving. Tool '{tool_name}' blocked. Use Relinquish to let the agent run tools.")
        return Proceed()

    def on_before_model_call(self, event: BeforeModelCallEvent):
        return Proceed()  # Always allow thinking/responding.

    def on_after_tool_call(self, event: AfterToolCallEvent):
        return Proceed()

    def on_after_model_call(self, event: AfterModelCallEvent):
        return Proceed()
