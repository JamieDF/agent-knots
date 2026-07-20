"""Event types shared across the cockpit, session manager, and Strands bridge.

These are the structured events that flow through the system. Strands hook
events are translated into these types for consumption by TUI and web UIs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    MESSAGE = "message"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    BLOCKER = "blocker"
    PROGRESS = "progress"
    STATE_CHANGE = "state_change"
    ERROR = "error"


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
