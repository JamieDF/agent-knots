"""Textual TUI cockpit.

Two screens:
  - OverviewScreen: agent list with DataTable, stats bar, keyboard shortcuts.
  - FocusScreen: per-agent event stream with assume/relinquish controls.

Keyboard shortcuts:
  j/↓ — move cursor down
  k/↑ — move cursor up
  Enter/f — focus selected agent
  Esc/b   — back to overview
  a       — assume control (focus view)
  r       — relinquish (focus view)
  q       — quit
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static
from textual import events

from agentjam.events import Event, EventType
from agentjam.session.manager import Session, SessionManager

# ── helpers ──────────────────────────────────────────────────────────────────


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}m{s:02d}s"


def _format_event_for_display(evt: Event) -> str:
    """Format an event as a single display line for the focus view."""
    if evt.type == EventType.MESSAGE:
        msg = evt.message[:80].replace("\n", " ")
        return f"[bold cyan]A[/] {msg}"
    if evt.type == EventType.THINKING:
        msg = evt.message[:80].replace("\n", " ")
        return f"[dim italic]T {msg}[/]"
    if evt.type == EventType.TOOL_CALL and evt.tool_call:
        name = evt.tool_call.name
        args = ", ".join(f"{k}={v}" for k, v in evt.tool_call.args.items())[:60]
        return f"[bold yellow]⚙ {name}[/] {args}"
    if evt.type == EventType.TOOL_RESULT:
        return f"  [dim green]✓ {evt.message[:60]}[/]"
    if evt.type == EventType.ERROR:
        return f"[bold red]! {evt.error or evt.message}[/]"
    if evt.type == EventType.BLOCKER:
        return f"[bold yellow]? {evt.message}[/]"
    if evt.type == EventType.STATE_CHANGE:
        return f"[dim]⚡ {evt.message}[/]"
    return evt.message[:80]


# ── overview screen ──────────────────────────────────────────────────────────


class OverviewScreen(Screen):
    """Screen showing all active agents in a DataTable."""

    CSS = """
    OverviewScreen {
        background: #12141a;
    }
    #overview-table {
        height: 1fr;
        border: none;
    }
    #overview-stats {
        height: 1;
        padding: 0 2;
        background: #1c1e26;
        color: #a0a0b0;
    }
    DataTable > .datatable--header {
        background: #242630;
        color: #a0a0b0;
    }
    DataTable > .datatable--cursor {
        background: #2a2a3a;
        color: #e4e4e8;
    }
    """

    BINDINGS = [
        ("j,down", "cursor_down", "Down"),
        ("k,up", "cursor_up", "Up"),
        ("enter,f", "focus_agent", "Focus"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, session_manager: SessionManager) -> None:
        super().__init__()
        self.session_manager = session_manager
        self._agents: list[Session] = []
        self._poll_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("", id="overview-stats")
        yield DataTable(id="overview-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#overview-table", DataTable)
        table.add_columns("ID", "Mode", "Status", "Tokens", "Cost", "Action")
        table.cursor_type = "row"
        self._poll_task = asyncio.create_task(self._poll_agents())

    async def _poll_agents(self) -> None:
        """Poll the session manager every 2 seconds for agent updates."""
        while True:
            try:
                await self._refresh()
            except Exception:
                pass
            await asyncio.sleep(2)

    async def _refresh(self) -> None:
        table = self.query_one("#overview-table", DataTable)
        stats = self.query_one("#overview-stats", Label)

        agents = self.session_manager.active
        self._agents = agents

        table.clear()
        for a in agents:
            status = "● running" if a.running else "○ idle"
            mode_display = f"⚠ {a.mode}" if a.mode == "assistant" else a.mode
            table.add_row(
                a.id,
                mode_display,
                status,
                str(a.tokens_used),
                f"${a.cost_usd:.3f}",
                a.task_id or "",
            )

        total_tokens = sum(a.tokens_used for a in agents)
        total_cost = sum(a.cost_usd for a in agents)
        stats.update(
            f" {len(agents)} agent{'s' if len(agents) != 1 else ''}"
            f" | {total_tokens} tok"
            f" | ${total_cost:.2f}"
        )

    def action_cursor_down(self) -> None:
        table = self.query_one("#overview-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        table = self.query_one("#overview-table", DataTable)
        table.action_cursor_up()

    def action_focus_agent(self) -> None:
        table = self.query_one("#overview-table", DataTable)
        row_key = table.cursor_row
        row = table.get_row_at(row_key) if row_key is not None else None
        if row is not None:
            agent_id = str(row[0])
            session = self.session_manager.get(agent_id)
            if session:
                self.app.push_screen(FocusScreen(session, self.session_manager))

    def action_quit(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        self.app.exit()


# ── focus screen ─────────────────────────────────────────────────────────────


class FocusScreen(Screen):
    """Screen showing the event stream for a single agent."""

    CSS = """
    FocusScreen {
        background: #12141a;
    }
    #focus-header {
        height: 3;
        padding: 0 2;
        background: #1c1e26;
        border-bottom: solid #2a2a3a;
    }
    #focus-events {
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #focus-footer {
        height: 1;
        padding: 0 2;
        background: #1c1e26;
        border-top: solid #2a2a3a;
        color: #6b6b80;
    }
    """

    BINDINGS = [
        ("escape,b", "back", "Back"),
        ("a", "assume", "Assume"),
        ("r", "relinquish", "Relinquish"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, session: Session, session_manager: SessionManager) -> None:
        super().__init__()
        self.session = session
        self.session_manager = session_manager
        self._events: list[str] = []
        self._watch_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f" Agent: {self.session.id}  |  Mode: {self.session.mode}", id="focus-header"),
            VerticalScroll(Static("Waiting for events...", id="events-static"), id="focus-events"),
            Label("  a: assume  |  r: relinquish  |  esc: back  |  q: quit", id="focus-footer"),
        )

    def on_mount(self) -> None:
        self._watch_task = asyncio.create_task(self._watch_events())

    async def _watch_events(self) -> None:
        """Continuously read events from the session queue."""
        static = self.query_one("#events-static", Static)
        first = True
        while True:
            try:
                evt = await asyncio.wait_for(self.session.event_stream.get(), timeout=1.0)
                if first:
                    first = False
                line = _format_event_for_display(evt)
                self._events.append(line)
                # Keep last 500 events to avoid memory issues.
                if len(self._events) > 500:
                    self._events = self._events[-500:]
                static.update("\n".join(self._events))
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def action_back(self) -> None:
        if self._watch_task:
            self._watch_task.cancel()
        self.app.pop_screen()

    async def action_assume(self) -> None:
        await self.session_manager.set_mode(self.session.id, "assistant")
        header = self.query_one("#focus-header", Label)
        header.update(f" Agent: {self.session.id}  |  Mode: assistant [dim](driving)[/]")

    async def action_relinquish(self) -> None:
        await self.session_manager.set_mode(self.session.id, "agent")
        header = self.query_one("#focus-header", Label)
        header.update(f" Agent: {self.session.id}  |  Mode: agent [dim](watching)[/]")

    def action_quit(self) -> None:
        if self._watch_task:
            self._watch_task.cancel()
        self.app.exit()


# ── app ──────────────────────────────────────────────────────────────────────


class CockpitApp(App):
    """The agentjam TUI cockpit."""

    TITLE = "agentjam cockpit"
    SCREENS = {}  # managed manually

    def __init__(self, session_manager: SessionManager) -> None:
        super().__init__()
        self.session_manager = session_manager

    def on_mount(self) -> None:
        self.push_screen(OverviewScreen(self.session_manager))
