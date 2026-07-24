"""Event types shared across the cockpit, session manager, and Strands bridge.

These are the structured events that flow through the system. Strands hook
events are translated into these types for consumption by TUI and web UIs.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    MESSAGE = "message"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    # No backend code broadcasts this yet — the frontend (AgentThread's
    # EventRow "blocker"/"ask" branch) and the TUI (app.py) both already
    # have real, working rendering for it, waiting on a producer that was
    # never built. Not dead code — a half-built feature. See docs/RETRO.md.
    BLOCKER = "blocker"
    STATE_CHANGE = "state_change"
    ERROR = "error"
    # Atelier event kinds — see events.py's serialize_event() for the wire
    # format these are sent in over SSE.
    AUTO_LOG = "auto_log"
    STEER = "steer"
    DELEGATE = "delegate"
    CHECKPOINT = "checkpoint"
    USER = "user"
    ENDED = "ended"


@dataclass
class ToolCall:
    """Describes a tool invocation by the agent."""

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Outcome of a tool invocation."""

    tool_call_id: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    error: str = ""


@dataclass
class Event:
    """A structured event from an agent session."""

    type: EventType
    session_id: str
    timestamp: float = field(default_factory=time.time)
    message: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    error: str = ""
    data: dict[str, Any] | None = None


def serialize_event(event: Event) -> dict[str, Any]:
    """Serialize an Event to a JSON-safe dict for the SSE wire format.

    Replaces the old format_event_html() approach — the frontend now
    owns all rendering, so this just needs to be a faithful JSON mirror
    of the dataclass (with `type` as its string value).
    """
    d = asdict(event)
    d["type"] = event.type.value
    return d
