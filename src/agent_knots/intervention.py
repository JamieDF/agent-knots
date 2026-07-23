"""Mode-aware intervention handler for reviewer/security read-only modes.

'agent' (autonomous) and 'assistant' (paused/interactive) both let tools
run freely — the difference between them is orchestration (does the
session keep pursuing its task on its own, see SessionManager.
set_autonomous()), not tool permission. Only 'reviewer'/'security' are
genuinely read-only: those modes deny every tool call so the agent can
analyse and comment but never make changes.

Future: use Confirm to prompt the user for each tool call, if a
per-tool-call approval flow is ever wanted for reviewer/security modes.
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
    """Intervention handler that denies tool calls in read-only modes.

    - agent / assistant mode: Proceed — tools always execute
    - reviewer/security mode: Deny — read-only, no tool execution

    IMPORTANT: override names must exactly match strands.interventions.
    InterventionHandler's base-class method names (before_tool_call, not
    on_before_tool_call) — the registry only wires up a hook for methods
    it detects as overridden via `getattr(type(handler), name) !=
    getattr(InterventionHandler, name)`, checked by exact name. A
    previous version of this file used on_-prefixed names that didn't
    match anything, so none of these were ever actually registered —
    every mode's tool calls proceeded unconditionally, silently, with no
    test catching it. See docs/RETRO.md.
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
        return mode in ("reviewer", "security")

    def before_tool_call(self, event: BeforeToolCallEvent):
        if self._is_restricted():
            tool_name = event.selected_tool.__name__ if event.selected_tool else "unknown"
            return Deny(reason=f"Read-only mode — tool '{tool_name}' blocked.")
        return Proceed()

    def before_model_call(self, event: BeforeModelCallEvent):
        return Proceed()  # Always allow thinking/responding.

    def after_tool_call(self, event: AfterToolCallEvent):
        return Proceed()

    def after_model_call(self, event: AfterModelCallEvent):
        return Proceed()
