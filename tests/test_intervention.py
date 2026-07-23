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
