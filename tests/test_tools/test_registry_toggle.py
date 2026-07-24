"""Tests for ToolRegistry.toggle() — previously had zero coverage.

toggle() unifies the "try custom, then built-in" branching that used to
be duplicated between the web server and the TUI (found in the code
review) — the TUI's copy didn't check built-in membership before
assuming a name was one, so toggling a genuinely nonexistent tool there
silently no-opped instead of raising. This is the one place that logic
now lives.
"""

import pytest

from agent_knots.tools.defaults import DEFAULT_TOOLS
from agent_knots.tools.registry import CustomTool, ToolRegistry


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))


class TestToggle:
    def test_toggles_a_custom_tool(self):
        registry = ToolRegistry()
        registry.add_custom(CustomTool(name="my_tool", command="echo hi"))

        result = registry.toggle("my_tool")

        assert result.enabled is False  # started enabled, now disabled
        assert registry.get_custom("my_tool").enabled is False

    def test_toggling_custom_twice_re_enables(self):
        registry = ToolRegistry()
        registry.add_custom(CustomTool(name="my_tool", command="echo hi"))

        registry.toggle("my_tool")
        result = registry.toggle("my_tool")

        assert result.enabled is True

    def test_toggles_a_builtin_tool(self):
        builtin_name = DEFAULT_TOOLS[0].__name__
        registry = ToolRegistry()

        result = registry.toggle(builtin_name)

        assert result.enabled is False
        assert builtin_name not in {t.name for t in registry.list_builtin() if t.enabled}

    def test_custom_tool_takes_precedence_over_a_same_named_builtin_shadow_attempt(self):
        # add_custom() itself refuses to shadow a builtin name, so this
        # just confirms toggle() checks get_custom() first as documented
        # — a custom tool with a unique name still resolves as custom,
        # not accidentally falling through to the builtin branch.
        registry = ToolRegistry()
        registry.add_custom(CustomTool(name="my_custom_tool", command="echo hi"))
        assert registry.toggle("my_custom_tool").enabled is False

    def test_unknown_name_raises_value_error(self):
        registry = ToolRegistry()
        with pytest.raises(ValueError, match="not found"):
            registry.toggle("definitely_not_a_real_tool")
