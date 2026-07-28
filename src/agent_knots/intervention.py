"""Mode-aware intervention handler for reviewer/security read-only modes,
plus an optional per-session tool allowlist for advisory agents.

'agent' (autonomous) and 'assistant' (paused/interactive) both let tools
run freely — the difference between them is orchestration (does the
session keep pursuing its task on its own, see SessionManager.
set_autonomous()), not tool permission. Only 'reviewer'/'security' are
genuinely read-only: those modes deny every tool call so the agent can
analyse and comment but never make changes.

The mode gate is all-or-nothing, though — it denies *every* tool,
including read_task/log_progress. An advisory agent (a reviewer role
sharing another session's working tree, see Session.advisory) needs to
call those to actually report its findings, so it's not gated by mode
at all; it's gated by an explicit allowlist instead (Session.
allowed_tools), which wins over mode entirely when set.

Future: use Confirm to prompt the user for each tool call, if a
per-tool-call approval flow is ever wanted for reviewer/security modes.
"""

from __future__ import annotations

from collections.abc import Callable

from strands.hooks.events import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
)
from strands.interventions import InterventionHandler
from strands.interventions.actions import Deny, Proceed

# Always permitted when an allowlist is active, regardless of what the
# allowlist itself contains — an advisory agent must always be able to
# read the task it's observing and report findings on it, even if
# whoever configured its Role.tools forgot to list these explicitly.
ALWAYS_ALLOWED_WITH_ALLOWLIST = frozenset({"read_task", "log_progress"})


class ModeInterventionHandler(InterventionHandler):
    """Intervention handler that denies tool calls in read-only modes,
    or restricts them to an explicit allowlist when one is set.

    - allowlist set (not None): Proceed only for tools in the allowlist
      (plus ALWAYS_ALLOWED_WITH_ALLOWLIST) — wins over mode entirely,
      so switching an advisory session's mode in the UI can't turn it
      into a second writer on the working tree it shares.
    - allowlist is None, agent/assistant mode: Proceed — tools always execute
    - allowlist is None, reviewer/security mode: Deny — read-only

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

    def __init__(
        self,
        get_mode: Callable[[], str],
        get_allowed_tools: Callable[[], set[str] | None] = lambda: None,
    ) -> None:
        super().__init__()
        self._get_mode = get_mode
        self._get_allowed_tools = get_allowed_tools

    @property
    def name(self) -> str:
        return "mode-intervention"

    def _is_restricted(self) -> bool:
        """Return True if tool execution should be blocked."""
        mode = self._get_mode()
        return mode in ("reviewer", "security")

    def before_tool_call(self, event: BeforeToolCallEvent):
        tool_name = event.selected_tool.__name__ if event.selected_tool else "unknown"

        allowed = self._get_allowed_tools()
        if allowed is not None:
            if tool_name in allowed or tool_name in ALWAYS_ALLOWED_WITH_ALLOWLIST:
                return Proceed()
            return Deny(reason=f"Not in this session's tool allowlist — '{tool_name}' blocked.")

        if self._is_restricted():
            return Deny(reason=f"Read-only mode — tool '{tool_name}' blocked.")
        return Proceed()

    def before_model_call(self, event: BeforeModelCallEvent):
        return Proceed()  # Always allow thinking/responding.

    def after_tool_call(self, event: AfterToolCallEvent):
        return Proceed()

    def after_model_call(self, event: AfterModelCallEvent):
        return Proceed()
