"""Session lifecycle management.

A Session wraps a running Strands Agent. The SessionManager handles
creating, tracking, and tearing down sessions. Strands hook events are
translated into agentjam Event objects and pushed onto an asyncio.Queue
for consumption by the cockpit UIs (TUI + web).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentjam.events import Event, EventType, ToolCall
from agentjam.vault.store import VaultStore

# ── Strands imports ──────────────────────────────────────────────────────────

try:
    from strands import Agent
    from strands.sandbox import PosixShellSandbox
    HAS_STRANDS = True
except ImportError:
    HAS_STRANDS = False


# ── session ──────────────────────────────────────────────────────────────────


@dataclass
class Session:
    """A running agent session wrapping a Strands Agent."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    mode: str = "agent"
    task_id: str | None = None
    project_id: str | None = None
    working_dir: str | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0

    # Internal — not serialised.
    _events: asyncio.Queue[Event] = field(default_factory=asyncio.Queue, repr=False)
    _agent: Any = field(default=None, repr=False)       # strands.Agent
    _task: asyncio.Task[Any] | None = field(default=None, repr=False)
    _cancelled: bool = field(default=False, repr=False)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def event_stream(self) -> asyncio.Queue[Event]:
        return self._events

    async def cancel(self) -> None:
        """Cancel the running agent task."""
        self._cancelled = True
        if self._agent is not None and hasattr(self._agent, "cancel"):
            try:
                await self._agent.cancel()
            except Exception:
                pass
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


# ── session manager ──────────────────────────────────────────────────────────


class SessionManager:
    """Creates, tracks, and tears down Strands-powered agent sessions."""

    def __init__(self, sessions_dir: Path, vault: VaultStore | None = None) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.vault = vault
        self._sessions: dict[str, Session] = {}

    @property
    def active(self) -> list[Session]:
        return list(self._sessions.values())

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def start(
        self,
        *,
        model: str = "",
        api_key: str = "",
        base_url: str | None = None,
        system_prompt: str = "",
        task_description: str | None = None,
        working_dir: str | None = None,
        mode: str = "agent",
        task_id: str | None = None,
        project_id: str | None = None,
        tools: list[Any] | None = None,
    ) -> Session:
        """Start a new Strands-powered agent session.

        Args:
            model: Model identifier. Empty = resolve from env/settings.
            api_key: API key. Empty = resolve from env/settings.
            base_url: Optional custom API base URL (MiniMax, local LLMs, etc.).
            system_prompt: System prompt for the agent.
            task_description: Initial task/message to send.
            working_dir: Working directory to bind into the sandbox.
            mode: Agent mode (agent, assistant, reviewer, security).
            task_id: Optional task ID reference.
            project_id: Optional project ID reference.
            tools: Optional list of Strands tools.

        Returns:
            The created Session.
        """
        if not HAS_STRANDS:
            raise RuntimeError(
                "Strands SDK is not installed. "
                "Install with: pip install strands-agents"
            )

        # Resolve provider config from CLI/env/settings.
        from agentjam.provider import resolve_provider

        provider = resolve_provider(model=model, api_key=api_key, base_url=base_url)
        if not provider.is_configured:
            raise RuntimeError(
                "No API key configured. Set one via:\n"
                "  export AGENTJAM_API_KEY=<your-key>\n"
                "  export AGENTJAM_MODEL=<model-id>\n"
                "Or add to ~/.agentjam/settings.yaml:\n"
                "  agent:\n"
                "    api_key: <your-key>\n"
                "    default_model: openai/gpt-4o-mini"
            )

        session_id = uuid.uuid4().hex[:12]

        # Create the model. Strands expects a model instance, not a config dict.
        # For OpenAI-compatible providers, use OpenAIModel with client_args.
        from strands.models.openai import OpenAIModel

        client_args: dict[str, Any] = {}
        if provider.api_key:
            client_args["api_key"] = provider.api_key
        if provider.base_url:
            client_args["base_url"] = provider.base_url

        model_instance = OpenAIModel(
            model_id=provider.model,
            client_args=client_args or None,
        )

        # Build the sandbox (optional — None means no filesystem sandboxing).
        sandbox = None
        if working_dir:
            sandbox_kwargs: dict[str, Any] = {"workspace": str(working_dir)}
            try:
                sandbox = PosixShellSandbox(**sandbox_kwargs)
            except (TypeError, NotImplementedError):
                pass

        # Create the agent.
        agent = Agent(
            model=model_instance,
            tools=tools or [],
            system_prompt=system_prompt,
            sandbox=sandbox,
            agent_id=session_id,
        )

        session = Session(
            id=session_id,
            mode=mode,
            task_id=task_id,
            project_id=project_id,
            working_dir=working_dir,
            _agent=agent,
        )
        self._sessions[session_id] = session

        # Start the agent in the background.
        if task_description:
            session._task = asyncio.create_task(
                self._run_agent(session, agent, task_description)
            )

        return session

    async def stop(self, session_id: str) -> None:
        """Stop a running session."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        await session.cancel()
        await session._events.put(Event(
            type=EventType.STATE_CHANGE,
            session_id=session_id,
            message="Session stopped.",
        ))

    async def send(self, session_id: str, message: str) -> None:
        """Send a follow-up message to an agent session.

        Awaits completion of any in-progress turn before starting a new one.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} not found")
        if session._agent is None:
            raise RuntimeError("agent not initialised")

        # Wait for previous turn to fully complete.
        if session._task is not None and not session._task.done():
            try:
                await asyncio.wait_for(session._task, timeout=30.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # Yield to let the event loop process the task's final cleanup.
        await asyncio.sleep(0)

        session._task = asyncio.create_task(
            self._run_agent(session, session._agent, message)
        )

    async def set_mode(self, session_id: str, mode: str) -> None:
        """Change the agent's mode (agent ↔ assistant).

        Implemented via Strands interventions — when mode is 'assistant'
        (user driving), we register an intervention handler that pauses
        before each tool call to wait for user approval.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} not found")

        session.mode = mode
        await session._events.put(Event(
            type=EventType.STATE_CHANGE,
            session_id=session_id,
            message=f"Mode changed to {mode}",
        ))

    # ── internals ─────────────────────────────────────────────────────────

    async def _run_agent(
        self,
        session: Session,
        agent: Agent,
        prompt: str,
    ) -> None:
        """Run the agent with a prompt, pushing events to the session queue."""
        finished = False
        try:
            await session._events.put(Event(
                type=EventType.STATE_CHANGE,
                session_id=session.id,
                message="Agent started.",
            ))

            chunk_state: dict[str, Any] = {}

            async for chunk in agent.stream_async(prompt):
                if session._cancelled:
                    break

                event = self._chunk_to_event(session.id, chunk, chunk_state)
                if event is not None:
                    await session._events.put(event)

            if not session._cancelled:
                finished = True
                await session._events.put(Event(
                    type=EventType.STATE_CHANGE,
                    session_id=session.id,
                    message="Agent finished.",
                ))

        except asyncio.CancelledError:
            if not finished:
                await session._events.put(Event(
                    type=EventType.STATE_CHANGE,
                    session_id=session.id,
                    message="Agent cancelled.",
                ))
        except Exception as exc:
            await session._events.put(Event(
                type=EventType.ERROR,
                session_id=session.id,
                error=str(exc),
                message=f"Agent error: {exc}",
            ))
        finally:
            session._cancelled = False

    @staticmethod
    def _chunk_to_event(session_id: str, chunk: Any, _state: dict[str, Any] | None = None) -> Event | None:
        """Translate a Strands stream chunk into an agentjam Event.

        Uses _state dict to track accumulated text and avoid duplicates
        (Strands sends both incremental contentBlockDelta and accumulated
        data+delta for the same text).
        """
        if _state is None:
            _state = {}

        now = time.time()

        if not isinstance(chunk, dict):
            return None

        # Lifecycle bookmarks — skip.
        if any(k in chunk for k in ('init_event_loop', 'start', 'start_event_loop',
                                       'force_stop', 'force_stop_reason')):
            return None

        # Text delta from content block — skip these, we use data+delta instead.
        # contentBlockDelta and data+delta overlap; data+delta gives us the
        # accumulated text which we can diff to emit only new portions.
        if 'event' in chunk:
            return None

        # Accumulated text delta — only emit the new portion.
        if 'data' in chunk and 'delta' in chunk:
            delta = chunk['delta'].get('text', '')
            if delta:
                prev = _state.get('last_data_text', '')
                if delta != prev:
                    # Find the new text: delta = prev + new
                    new_text = delta
                    if delta.startswith(prev):
                        new_text = delta[len(prev):]
                    _state['last_data_text'] = delta
                    return Event(
                        type=EventType.THINKING if _is_thinking(new_text) else EventType.MESSAGE,
                        session_id=session_id,
                        message=new_text,
                        timestamp=now,
                    )
            return None

        # Final message.
        if 'message' in chunk:
            msg = chunk['message']
            content = msg.get('content', '')
            if isinstance(content, list):
                # Content blocks — extract text.
                text = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
            else:
                text = str(content)
            # Check if it's a thinking block.
            if '<think>' in text:
                # Extract thinking and response separately.
                parts = text.split('</think>')
                if len(parts) > 1:
                    return Event(
                        type=EventType.MESSAGE,
                        session_id=session_id,
                        message=parts[-1].strip(),
                        timestamp=now,
                    )
            return Event(
                type=EventType.MESSAGE,
                session_id=session_id,
                message=text,
                timestamp=now,
            )

        # Result — final completion.
        if 'result' in chunk:
            return Event(
                type=EventType.STATE_CHANGE,
                session_id=session_id,
                message='Agent finished.',
                timestamp=now,
            )

        # Fallback — any dict with text-like content.
        for key in ('text', 'content', 'output'):
            if key in chunk:
                return Event(
                    type=EventType.MESSAGE,
                    session_id=session_id,
                    message=str(chunk[key]),
                    timestamp=now,
                )

        return None


def _is_thinking(text: str) -> bool:
    """Heuristic: detect if text is inside a <think> block."""
    return '<think>' in text or text.strip().startswith('</think>')
