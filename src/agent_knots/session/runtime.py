"""Session runtimes.

One implementation: InProcessRuntime, which runs the agent in the same
Python process. A second, SubprocessRuntime (spawning a child process
for isolation), existed here but was removed after it turned out to
never actually work. It referenced a Session API (session._events) that
stopped existing when
the SSE fan-out fix replaced the single queue with
_subscribers/_history/_broadcast(), so it crashed on the first event any
subprocess-runtime session tried to emit, and had zero test coverage
catching that. Its own event-chunk parser had also independently
drifted from the (fixed) one in session/manager.py, so restoring it
would have meant fixing two bugs and then keeping two parsers in sync
going forward for a mode nothing currently selects by default and that
never worked when selected. Real process-level isolation is still a
real, wanted feature — see the container runtime item on the roadmap —
just not this implementation.

The abstraction is kept as a single-member setup (rather than inlining
InProcessRuntime directly into SessionManager) specifically so a real
isolated runtime — container-backed, most likely — can be added later
without changing SessionManager's own code, only create_runtime().
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from agent_knots.session.manager import Session


class SessionRuntime(ABC):
    """Abstract runtime for running an agent session."""

    @abstractmethod
    async def start(self, session: Session, config: dict) -> None:
        """Start the agent. Events should be pushed to session._events."""
        ...

    @abstractmethod
    async def stop(self, session: Session) -> None:
        """Stop the agent."""
        ...

    @abstractmethod
    async def send(self, session: Session, message: str) -> None:
        """Send a message to a running agent."""
        ...

    @abstractmethod
    async def set_mode(self, session: Session, mode: str) -> None:
        """Change the agent's mode."""
        ...


class InProcessRuntime(SessionRuntime):
    """Runs the agent in the same Python process (current behavior)."""

    def __init__(self, session_manager: Any) -> None:
        self._mgr = session_manager

    async def start(self, session: Session, config: dict) -> None:
        """Fire up the agent in a background asyncio task on this process."""
        task_description = config.get("task_description", "")
        if task_description and session._agent is not None:
            session._task = asyncio.create_task(
                self._mgr._run_agent(session, session._agent, task_description)
            )

    async def stop(self, session: Session) -> None:
        await session.cancel()

    async def send(self, session: Session, message: str) -> None:
        await self._mgr.send(session.id, message)

    async def set_mode(self, session: Session, mode: str) -> None:
        await self._mgr.set_mode(session.id, mode)


# ── runtime factory ──────────────────────────────────────────────────────────

_RUNTIME_TYPE = "inprocess"


def set_runtime_type(runtime_type: str) -> None:
    """Set the global runtime type. Only "inprocess" is real; anything
    else (including "subprocess", still accepted from settings/project
    files saved before it was removed) is silently treated as
    "inprocess" by create_runtime() below rather than rejected — an
    old saved value shouldn't suddenly break sessions on upgrade."""
    global _RUNTIME_TYPE
    if runtime_type == "inprocess":
        _RUNTIME_TYPE = runtime_type


def get_runtime_type() -> str:
    return _RUNTIME_TYPE


def create_runtime(session_manager: Any = None, runtime_type: str | None = None) -> SessionRuntime:
    """Create a runtime for the given type, or the global setting if omitted.

    Callers that have already resolved a runtime type (e.g. from a project
    override) should pass it explicitly rather than relying on the global —
    the global reflects only the last call to set_runtime_type() and can be
    stale relative to a per-session/per-project resolution.

    Only "inprocess" is implemented — any other value (including the
    removed "subprocess") falls back to it rather than raising, so a
    pre-existing settings.yaml/project.yaml with an old runtime value
    keeps working instead of crashing session start.
    """
    return InProcessRuntime(session_manager)
