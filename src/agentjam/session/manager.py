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
            system_prompt: System prompt for the agent (appended to task context).
            task_description: Initial task/message to send.
            working_dir: Working directory to bind into the sandbox.
            mode: Agent mode (agent, assistant, reviewer, security).
            task_id: Optional task ID. If set, task details are included in
                     the system prompt so the agent knows what to work on.
            project_id: Optional project ID reference.
            tools: Optional list of Strands tools. Task tools are always included.

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

        # Resolve task context if a task_id was provided.
        task_context = ""
        if task_id:
            from agentjam.task.store import TaskStore
            from agentjam.task.models import TaskStatus
            from agentjam.config import tasks_dir as _tasks_dir
            store = TaskStore(_tasks_dir())
            task = store.get(task_id)
            if task:
                task_context = _build_task_prompt(task)
                # Assign the task to this session and move to in_progress.
                store.assign(task_id, session_id)
                if task.status.value == "open":
                    store.set_status(task_id, TaskStatus("in_progress"))

        # Build the full system prompt with task context.
        full_prompt = _build_system_prompt(system_prompt, task_context, mode)

        # Always include default tools + enabled custom tools from registry.
        from agentjam.tools.defaults import DEFAULT_TOOLS, auto_approve_tools
        from agentjam.tools.registry import ToolRegistry

        auto_approve_tools()
        registry = ToolRegistry()
        all_tools = list(tools or []) + registry.list_enabled()

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

        # Determine working directory: explicit > workspace repo > cwd.
        resolved_working_dir = working_dir
        if not resolved_working_dir and project_id:
            # Look up the workspace's repository path.
            from agentjam.project.store import ProjectStore
            from agentjam.config import projects_dir as _projects_dir
            ps = ProjectStore(_projects_dir())
            proj = ps.get(project_id)
            if proj and proj.repository:
                resolved_working_dir = proj.repository

        # Swap in sandboxed shell/editor tools if we have a workspace.
        ws_sandbox = None
        if resolved_working_dir:
            from agentjam.isolation import create_sandbox
            ws_sandbox = create_sandbox(str(resolved_working_dir))

        if ws_sandbox and ws_sandbox.exists:
            from agentjam.sandbox_tools import make_sandboxed_shell, make_sandboxed_editor
            ws = ws_sandbox.workspace_dir
            sb_shell = make_sandboxed_shell(ws)
            sb_editor = make_sandboxed_editor(ws)
            all_tools = [
                sb_shell if getattr(t, '__name__', '') == 'shell'
                else sb_editor if getattr(t, '__name__', '') == 'editor'
                else t
                for t in all_tools
            ]

        # Create the agent.
        agent = Agent(
            model=model_instance,
            tools=all_tools,
            system_prompt=full_prompt,
            sandbox=None,
            agent_id=session_id,
        )

        session = Session(
            id=session_id,
            mode=mode,
            task_id=task_id,
            project_id=project_id,
            working_dir=resolved_working_dir,
            _agent=agent,
        )
        self._sessions[session_id] = session

        # Choose runtime based on global setting.
        from agentjam.session.runtime import get_runtime_type, create_runtime

        runtime_type = get_runtime_type()
        if runtime_type == "subprocess":
            # Subprocess runtime handles its own event streaming.
            runtime = create_runtime()
            await runtime.start(session, {
                "model": provider.model,
                "api_key": provider.api_key,
                "base_url": provider.base_url or "",
                "workspace_dir": resolved_working_dir or "",
                "system_prompt": full_prompt,
                "task_description": task_description or "",
            })
        else:
            # In-process: fire up the agent in a background task.
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
        # But tool use events also come through 'event' — handle those.
        if 'event' in chunk:
            evt = chunk['event']
            # Tool use start.
            if 'contentBlockStart' in evt:
                start = evt['contentBlockStart'].get('start', {})
                if 'toolUse' in start:
                    tu = start['toolUse']
                    return Event(
                        type=EventType.TOOL_CALL,
                        session_id=session_id,
                        tool_call=ToolCall(id=tu.get('toolUseId', ''), name=tu.get('name', ''), args={}),
                        timestamp=now,
                    )
            # Other events — skip.
            return None

        # Tool use streaming — accumulate input args.
        if chunk.get('type') == 'tool_use_stream':
            current = chunk.get('current_tool_use', {})
            return Event(
                type=EventType.TOOL_CALL,
                session_id=session_id,
                tool_call=ToolCall(
                    id=current.get('toolUseId', ''),
                    name=current.get('name', ''),
                    args=_parse_tool_input(current.get('input', '{}')),
                ),
                timestamp=now,
            )

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

        # Final message — check for tool results.
        if 'message' in chunk:
            msg = chunk['message']
            content = msg.get('content', '')
            if isinstance(content, list):
                # Check for tool result.
                for c in content:
                    if isinstance(c, dict) and 'toolResult' in c:
                        tr = c['toolResult']
                        result_text = ''
                        if isinstance(tr.get('content', []), list):
                            result_text = ' '.join(
                                ct.get('text', '') for ct in tr['content'] if isinstance(ct, dict)
                            )
                        return Event(
                            type=EventType.TOOL_RESULT,
                            session_id=session_id,
                            message=result_text,
                            data=tr,
                            timestamp=now,
                        )
                # Regular content blocks — extract text.
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


def _parse_tool_input(raw: str) -> dict:
    """Parse a tool input JSON string, returning empty dict on failure."""
    import json as _json
    try:
        return _json.loads(raw) if raw and raw != '{}' else {}
    except (_json.JSONDecodeError, TypeError):
        return {}


def _build_task_prompt(task: Any) -> str:
    """Build a task context block for the system prompt."""
    from agentjam.task.models import Task as TaskModel
    t: TaskModel = task
    parts = [
        "## Current Task",
        f"Task ID: {t.id}",
        f"Title: {t.title}",
        f"Status: {t.status.value}",
        f"Priority: {t.priority.value}",
    ]
    if t.description:
        parts.append(f"\nDescription:\n{t.description}")
    if t.acceptance_criteria:
        parts.append("\nAcceptance Criteria:")
        for c in t.acceptance_criteria:
            parts.append(f"  - {c}")
    if t.steps:
        parts.append("\nSteps:")
        for s in t.steps:
            icon = "✓" if s.status.value == "done" else "○" if s.status.value == "draft" else "●"
            parts.append(f"  {icon} {s.title} [{s.status.value}]")
    if t.progress:
        parts.append(f"\nProgress log ({len(t.progress)} entries, most recent last):")
        for p in t.progress[-5:]:
            parts.append(f"  [{p.status.value}] {p.entry}")
    parts.append("\nUse the task tools (create_task, read_task, log_progress, update_task_status, add_step, list_tasks) to manage this task. Log progress after every meaningful action.")
    return "\n".join(parts)


def _build_system_prompt(base_prompt: str, task_context: str, mode: str) -> str:
    """Assemble the full system prompt."""
    parts = []

    if base_prompt:
        parts.append(base_prompt)

    if mode == "agent":
        parts.append("You are an autonomous coding agent. You have tools for reading/writing files, running shell commands, editing code, and managing tasks. Work through tasks systematically. Log progress after every meaningful action using the task tools provided.")
    elif mode == "assistant":
        parts.append("You are a coding assistant working interactively with a user. You have tools for reading/writing files, running shell commands, editing code, and managing tasks. Ask clarifying questions when needed. Log progress using the task tools provided.")
    elif mode == "reviewer":
        parts.append("You are a code reviewer. Focus on finding issues, suggesting improvements, and verifying correctness. Do not make changes unless asked.")
    elif mode == "security":
        parts.append("You are a security auditor. Focus on finding vulnerabilities, unsafe patterns, and security anti-patterns. Do not make changes unless asked.")

    if task_context:
        parts.append(task_context)

    return "\n\n".join(parts)
