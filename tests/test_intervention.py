"""Tests for ModeInterventionHandler.

Previously had zero coverage — a real bug shipped silently as a result
(see docs/RETRO.md): the handler defined on_before_tool_call/etc., method
names that don't match strands.interventions.InterventionHandler's base
class, so InterventionRegistry's override-detection never registered any
hook at all. Every mode's tool calls proceeded unconditionally. These
tests assert both the behavior (right Action per mode) and the actual
registration with Strands' hook system, since the behavior-only check
would have passed even with the broken on_-prefixed names (calling the
method directly doesn't exercise the registry at all).
"""

from strands.hooks.events import BeforeToolCallEvent
from strands.hooks.registry import HookRegistry
from strands.interventions.actions import Deny, Proceed
from strands.interventions.registry import InterventionRegistry

from agent_knots.intervention import ModeInterventionHandler


class _FakeEvent:
    selected_tool = None


def _tool_event(name: str):
    event = _FakeEvent()
    event.selected_tool = type(name, (), {})  # a class named `name` has __name__ == name
    return event


class TestModeInterventionHandler:
    def test_before_tool_call_proceeds_in_agent_mode(self):
        handler = ModeInterventionHandler(get_mode=lambda: "agent")
        assert isinstance(handler.before_tool_call(_FakeEvent()), Proceed)

    def test_before_tool_call_proceeds_in_assistant_mode(self):
        """assistant (paused/interactive) is not read-only — tools still
        run, only the orchestration differs (SessionManager.
        set_autonomous()). Only reviewer/security genuinely deny."""
        handler = ModeInterventionHandler(get_mode=lambda: "assistant")
        assert isinstance(handler.before_tool_call(_FakeEvent()), Proceed)

    def test_before_tool_call_denies_in_reviewer_mode(self):
        handler = ModeInterventionHandler(get_mode=lambda: "reviewer")
        assert isinstance(handler.before_tool_call(_FakeEvent()), Deny)

    def test_before_tool_call_denies_in_security_mode(self):
        handler = ModeInterventionHandler(get_mode=lambda: "security")
        assert isinstance(handler.before_tool_call(_FakeEvent()), Deny)

    def test_handler_methods_actually_register_with_strands(self):
        """The regression test that would have caught the real bug:
        asserts the hook actually gets wired into Strands' registry, not
        just that calling the method directly returns the right Action."""
        handler = ModeInterventionHandler(get_mode=lambda: "reviewer")
        hook_registry = HookRegistry()
        assert not hook_registry.has_callbacks()  # nothing registered yet
        InterventionRegistry([handler], hook_registry)
        assert hook_registry.has_callbacks()  # before_tool_call got wired up
        assert bool(hook_registry.get_callbacks_for(BeforeToolCallEvent(
            agent=None, selected_tool=None, tool_use={}, invocation_state={},
        )))


class TestToolAllowlist:
    """Per-session tool allowlist — the escape hatch that lets an
    advisory agent call read_task/log_progress despite being read-only,
    since the blunt mode gate above denies every tool with no exceptions."""

    def test_allowed_tool_proceeds(self):
        handler = ModeInterventionHandler(
            get_mode=lambda: "agent", get_allowed_tools=lambda: {"read_task"},
        )
        assert isinstance(handler.before_tool_call(_tool_event("read_task")), Proceed)

    def test_unlisted_tool_denied_even_in_agent_mode(self):
        """The allowlist restricts even a normally-unrestricted mode —
        it's not just an addition to the mode gate, it replaces it."""
        handler = ModeInterventionHandler(
            get_mode=lambda: "agent", get_allowed_tools=lambda: {"read_task"},
        )
        assert isinstance(handler.before_tool_call(_tool_event("shell")), Deny)

    def test_always_allowed_tools_proceed_even_if_not_listed(self):
        """An advisory agent must always be able to report, even if
        whoever configured its Role.tools forgot read_task/log_progress."""
        handler = ModeInterventionHandler(
            get_mode=lambda: "agent", get_allowed_tools=lambda: {"editor"},
        )
        assert isinstance(handler.before_tool_call(_tool_event("read_task")), Proceed)
        assert isinstance(handler.before_tool_call(_tool_event("log_progress")), Proceed)

    def test_allowlist_wins_over_agent_mode(self):
        handler = ModeInterventionHandler(
            get_mode=lambda: "agent", get_allowed_tools=lambda: set(),
        )
        assert isinstance(handler.before_tool_call(_tool_event("shell")), Deny)

    def test_no_allowlist_falls_back_to_mode_agent(self):
        """None (the default) must behave identically to the pre-allowlist
        handler — no regression for every session that isn't advisory."""
        handler = ModeInterventionHandler(get_mode=lambda: "agent")
        assert isinstance(handler.before_tool_call(_tool_event("shell")), Proceed)

    def test_no_allowlist_falls_back_to_mode_reviewer(self):
        handler = ModeInterventionHandler(get_mode=lambda: "reviewer")
        assert isinstance(handler.before_tool_call(_tool_event("shell")), Deny)

    def test_default_get_allowed_tools_is_none(self):
        """Constructing without get_allowed_tools at all (every call
        site before this feature) must not change behaviour."""
        handler = ModeInterventionHandler(get_mode=lambda: "reviewer")
        assert handler._get_allowed_tools() is None
