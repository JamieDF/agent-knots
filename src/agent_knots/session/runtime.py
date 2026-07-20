"""Session runtimes — in-process vs subprocess.

Two implementations:
- InProcessRuntime: runs the agent in the same Python process (default)
- SubprocessRuntime: spawns a child process for isolation
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agent_knots.events import Event, EventType, ToolCall
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


class SubprocessRuntime(SessionRuntime):
    """Spawns a child process for agent isolation.

    The child runs `agent_knots.session.worker` which communicates via
    JSONL over stdin/stdout. Events are forwarded to the session's
    event queue.
    """

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._readers: dict[str, asyncio.Task] = {}

    async def start(self, session: Session, config: dict) -> None:
        """Spawn the worker subprocess and start streaming events."""
        # Build the config to send.
        worker_config = {
            "type": "config",
            "model": config.get("model", "minimax-m2.7"),
            "api_key": config.get("api_key", ""),
            "base_url": config.get("base_url", ""),
            "workspace_dir": config.get("workspace_dir", ""),
            "system_prompt": config.get("system_prompt", ""),
            "task_description": config.get("task_description", ""),
        }

        # The worker module path.
        worker_module = "agent_knots.session.worker"

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-m", worker_module,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.get("workspace_dir") or None,
        )

        self._processes[session.id] = proc

        # Send config.
        proc.stdin.write((json.dumps(worker_config) + "\n").encode())
        await proc.stdin.drain()

        # Start reading events from stdout.
        self._readers[session.id] = asyncio.create_task(
            self._read_events(session, proc)
        )

    async def _read_events(self, session: Session, proc: asyncio.subprocess.Process) -> None:
        """Read JSONL events from the subprocess stdout."""
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break

                try:
                    data = json.loads(line.decode().strip())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                msg_type = data.get("type", "")
                if msg_type == "event":
                    event = self._parse_event(session.id, data)
                    if event:
                        await session._events.put(event)
                elif msg_type == "done":
                    break
        except Exception:
            pass
        finally:
            await session._events.put(Event(
                type=EventType.STATE_CHANGE,
                session_id=session.id,
                message="Session ended.",
            ))

    async def stop(self, session: Session) -> None:
        proc = self._processes.pop(session.id, None)
        reader = self._readers.pop(session.id, None)

        if proc and proc.returncode is None:
            try:
                proc.stdin.write(b'{"type":"stop"}\n')
                await proc.stdin.drain()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                proc.kill()
                await proc.wait()

        if reader and not reader.done():
            reader.cancel()

    async def send(self, session: Session, message: str) -> None:
        proc = self._processes.get(session.id)
        if proc and proc.returncode is None:
            msg = json.dumps({"type": "send", "message": message}) + "\n"
            proc.stdin.write(msg.encode())
            await proc.stdin.drain()

    async def set_mode(self, session: Session, mode: str) -> None:
        proc = self._processes.get(session.id)
        if proc and proc.returncode is None:
            msg = json.dumps({"type": "set-mode", "mode": mode}) + "\n"
            proc.stdin.write(msg.encode())
            await proc.stdin.drain()
        session.mode = mode
        await session._events.put(Event(
            type=EventType.STATE_CHANGE,
            session_id=session.id,
            message=f"Mode changed to {mode}",
        ))

    @staticmethod
    def _parse_event(session_id: str, data: dict) -> Event | None:
        """Parse a subprocess event dict into an Event object."""
        event_type = data.get("event_type", "")
        now = time.time()

        mapping = {
            "message": EventType.MESSAGE,
            "thinking": EventType.THINKING,
            "tool_call": EventType.TOOL_CALL,
            "tool_result": EventType.TOOL_RESULT,
            "error": EventType.ERROR,
            "state_change": EventType.STATE_CHANGE,
        }

        etype = mapping.get(event_type, EventType.MESSAGE)

        tool_call = None
        if etype == EventType.TOOL_CALL:
            tool_call = ToolCall(
                id=str(uuid.uuid4())[:8],
                name=data.get("tool_name", ""),
                args=data.get("args", {}),
            )

        return Event(
            type=etype,
            session_id=session_id,
            timestamp=now,
            message=data.get("message", ""),
            error=data.get("error", ""),
            tool_call=tool_call,
        )


# ── runtime factory ──────────────────────────────────────────────────────────

_RUNTIME_TYPE = "inprocess"  # "inprocess" or "subprocess"


def set_runtime_type(runtime_type: str) -> None:
    """Set the global runtime type ('inprocess' or 'subprocess')."""
    global _RUNTIME_TYPE
    if runtime_type in ("inprocess", "subprocess"):
        _RUNTIME_TYPE = runtime_type


def get_runtime_type() -> str:
    return _RUNTIME_TYPE


def create_runtime(session_manager: Any = None, runtime_type: str | None = None) -> SessionRuntime:
    """Create a runtime for the given type, or the global setting if omitted.

    Callers that have already resolved a runtime type (e.g. from a project
    override) should pass it explicitly rather than relying on the global —
    the global reflects only the last call to set_runtime_type() and can be
    stale relative to a per-session/per-project resolution.
    """
    rt = runtime_type or _RUNTIME_TYPE
    if rt == "subprocess":
        return SubprocessRuntime()
    return InProcessRuntime(session_manager)
