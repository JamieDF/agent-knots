"""Session lifecycle management.

A Session wraps a running Strands Agent. The SessionManager handles
creating, tracking, and tearing down sessions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentjam.events import Event


@dataclass
class Session:
    """A running agent session."""

    id: str
    mode: str = "agent"
    task_id: str | None = None
    project_id: str | None = None
    working_dir: str | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    # Internal
    _events: asyncio.Queue[Event] = field(default_factory=asyncio.Queue, repr=False)
    _agent: Any = field(default=None, repr=False)  # strands.Agent instance

    @property
    def event_stream(self) -> asyncio.Queue[Event]:
        """The live event stream for this session."""
        return self._events


class SessionManager:
    """Creates, tracks, and tears down agent sessions."""

    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = Path(sessions_dir)
        self._sessions: dict[str, Session] = {}

    @property
    def active(self) -> list[Session]:
        """Return all active sessions."""
        return list(self._sessions.values())

    def get(self, session_id: str) -> Session | None:
        """Return a session by ID, or None."""
        return self._sessions.get(session_id)

    async def start(self, **opts: Any) -> Session:
        """Start a new session. Not yet implemented."""
        raise NotImplementedError("Session start not yet implemented")

    async def stop(self, session_id: str) -> None:
        """Stop a running session. Not yet implemented."""
        raise NotImplementedError("Session stop not yet implemented")
