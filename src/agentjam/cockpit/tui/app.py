"""Textual TUI cockpit.

Two main screens:
  - Overview: agent list with status cards, stats bar, keyboard shortcuts.
  - Focus: per-agent event stream view with assume/relinquish controls.
"""

from __future__ import annotations

from textual.app import App


class CockpitApp(App):
    """The agentjam TUI cockpit."""

    CSS = """
    Screen {
        background: #12141a;
    }
    """

    def on_mount(self) -> None:
        self.title = "agentjam cockpit"
