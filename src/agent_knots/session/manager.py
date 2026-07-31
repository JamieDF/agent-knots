"""Session lifecycle management.

A Session wraps a running Strands Agent. The SessionManager handles
creating, tracking, and tearing down sessions. Strands hook events are
translated into agent-knots Event objects and pushed onto an asyncio.Queue
for consumption by the cockpit UIs (TUI + web).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from agent_knots.events import Event, EventType, ToolCall, ToolResult
from agent_knots.gitutil import (
    BranchResult,
    branch_exists,
    current_branch,
    delete_branch_if_empty_async,
    ensure_session_branch_async,
    is_repo,
    session_branch_name,
)
from agent_knots.vault.store import VaultStore


class CancelKind(Enum):
    """Session._cancel_kind's three states — collapses what used to be
    two independent booleans (_cancelled, _interrupt_only) into one
    tri-state, since "not cancelled" / "cancelled, session ending" /
    "cancelled, session staying alive" were never actually four
    independent combinations — _interrupt_only was only ever meaningful
    when _cancelled was also True."""

    NONE = "none"
    INTERRUPT = "interrupt"  # current turn only — session stays alive
    STOP = "stop"  # the whole session is ending


class _SessionCredentialEnv:
    """Lazily resolves a task's required_credentials into shell env vars,
    memoised for a short TTL.

    A callable-backed cache rather than a one-shot dict so a vault
    unlocked *after* the session started still takes effect on the next
    shell call — but re-decrypting and re-auditing on literally every
    tool invocation would be wasteful and would spam the audit log, so
    resolution is only repeated after the TTL elapses.
    """

    _TTL = 30.0

    def __init__(self, vault: VaultStore, cred_ids: list[str], caller: str) -> None:
        self._vault = vault
        self._cred_ids = cred_ids
        self._caller = caller
        self._env: dict[str, str] = {}
        self._resolved_at = 0.0

    def resolve(self) -> tuple[dict[str, str], list[str]]:
        """Force a fresh resolution now. Called once eagerly at session
        start (so the system prompt can mention unavailable credentials
        from the first turn) and again by get_env() once the TTL lapses."""
        self._env, problems = self._vault.resolve_env(self._cred_ids, caller=self._caller)
        self._resolved_at = time.time()
        return self._env, problems

    def get_env(self) -> dict[str, str]:
        if time.time() - self._resolved_at > self._TTL:
            self.resolve()
        return self._env


# ── Strands imports ──────────────────────────────────────────────────────────

try:
    from strands import Agent
    HAS_STRANDS = True
except ImportError:
    HAS_STRANDS = False


# ── session ──────────────────────────────────────────────────────────────────


@dataclass
class Session:
    """A running agent session wrapping a Strands Agent."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # Human-readable display name ("sleepy-panda") — generated in
    # SessionManager.start() rather than via a bare default_factory here
    # since it needs to check uniqueness against currently-active
    # sessions, which this dataclass has no access to on its own.
    name: str = ""
    mode: str = "agent"
    task_id: str | None = None
    project_id: str | None = None
    working_dir: str | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    model: str = ""
    started_at: float = field(default_factory=time.time)

    # Git branch this session works on. None = no branch (not a repo, no
    # working dir, advisory session, or git refused — see
    # SessionManager._ensure_branch). branch_created distinguishes "we
    # made this" from "it already existed and we checked it out", which
    # is what stop() keys its cleanup off: we only ever delete branches
    # we created ourselves.
    branch: str | None = None
    branch_created: bool = False
    branch_base: str = ""
    # Advisory sessions are read-only observers sharing another session's
    # working tree (a reviewer role on the same task). They never create
    # or switch branches — the writer owns HEAD — and never take over the
    # task's assigned_to.
    advisory: bool = False
    # None = no allowlist, tool access follows mode as before. A set
    # restricts tool calls to exactly those names (plus
    # ALWAYS_ALLOWED_WITH_ALLOWLIST) regardless of mode — see
    # ModeInterventionHandler. Set on advisory sessions from Role.tools.
    allowed_tools: set[str] | None = None
    # Key of the Role (Workflows screen) that auto-fired this session,
    # if any — "" for a manually-started session. Display-only.
    role: str = ""

    # Internal — not serialised. Multiple SSE subscribers (e.g. two browser
    # tabs open on the same agent) each get their own queue rather than
    # racing on one — see Session.subscribe()/unsubscribe(). _history is a
    # bounded ring buffer replayed to new subscribers so a viewer opening
    # the stream late still sees prior events (and is the seed for a
    # future replay scrubber).
    #
    # 500 was too small in practice: a single tool call is re-broadcast
    # on every incremental chunk as its args stream in (confirmed live —
    # one log_progress call alone produced 50+ raw events), so a real
    # session with a handful of tool calls blows past 500 within a turn
    # or two. The oldest events then silently fall off the ring buffer,
    # which looked like "navigate away and back and the earlier part of
    # the conversation is just gone" even though nothing was actually
    # broken in the replay path itself. 20000 is generous enough that no
    # realistic session hits it, while still bounding worst-case memory
    # for a truly runaway agent.
    _subscribers: list[asyncio.Queue[Event]] = field(default_factory=list, repr=False)
    _history: list[Event] = field(default_factory=list, repr=False)
    _history_limit: int = field(default=20000, repr=False)
    _agent: Any = field(default=None, repr=False)       # strands.Agent
    _task: asyncio.Task[Any] | None = field(default=None, repr=False)
    # Set by cancel() — tells _run_agent's cancellation handler whether to
    # report this as an interrupted turn (STATE_CHANGE, composer stays
    # usable, a follow-up send() can start a new turn) or the session
    # actually ending (ENDED).
    _cancel_kind: CancelKind = field(default=CancelKind.NONE, repr=False)
    # PIDs of background=true shell commands (dev servers, watchers) this
    # session's agent has started — these deliberately outlive any single
    # turn/interrupt, but SessionManager.stop() kills them so they don't
    # outlive the session itself forever.
    _background_pids: list[int] = field(default_factory=list, repr=False)
    # System-prompt components stored so set_mode() can rebuild the prompt
    # when autonomous is toggled — otherwise the agent keeps the original
    # mode's instruction forever, even after mode changes.
    _base_prompt: str = field(default="", repr=False)
    _task_context: str = field(default="", repr=False)
    _workspace_context: str = field(default="", repr=False)
    # Pending ask_user question — a dict with keys: event (threading.Event),
    # answer (str), question (str), options (list[str] | None). The tool
    # blocks on the Event; the /api/agent/{id}/answer endpoint sets it.
    _pending_question: dict | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self) -> asyncio.Queue[Event]:
        """Register a new SSE subscriber, pre-seeded with recent history."""
        q: asyncio.Queue[Event] = asyncio.Queue()
        for event in self._history:
            q.put_nowait(event)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        """Remove a subscriber queue (e.g. on SSE client disconnect)."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    def _broadcast(self, event: Event) -> None:
        """Push an event to history and every live subscriber."""
        self._history.append(event)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit:]
        for q in self._subscribers:
            q.put_nowait(event)

    async def cancel(self, *, end_session: bool = True) -> None:
        """Cancel the running agent task.

        end_session=False is used by SessionManager.interrupt() — the
        current turn is cancelled but the session itself stays alive
        (see CancelKind.INTERRUPT).
        """
        self._cancel_kind = CancelKind.STOP if end_session else CancelKind.INTERRUPT
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
        # repo path -> session id of the writer that owns HEAD there.
        # git checkout is process-global, so two writer sessions in one
        # repo would fight over the working tree; the second one skips
        # branching rather than yanking files out from under the first.
        # This is the tradeoff worktrees would remove — see roadmap.md.
        self._repo_writers: dict[str, str] = {}

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
        runtime_override: str = "",
        advisory: bool = False,
        allowed_tools: list[str] | None = None,
        role: str = "",
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
            advisory: Read-only observer sharing another session's working
                      tree. Skips branch creation and does not claim the
                      task's assigned_to.
            allowed_tools: If given, restricts tool calls to exactly these
                      names (see ModeInterventionHandler) regardless of
                      mode. Typically a Role's tools list for an
                      advisory session; None elsewhere.
            role: Key of the Role that's auto-firing this session, if
                      any — display-only.

        Returns:
            The created Session.
        """
        if not HAS_STRANDS:
            raise RuntimeError(
                "Strands SDK is not installed. "
                "Install with: pip install strands-agents"
            )

        # Resolve provider config from CLI/env/settings.
        from agent_knots.provider import resolve_provider

        provider = resolve_provider(model=model, api_key=api_key, base_url=base_url)
        if not provider.is_configured:
            raise RuntimeError(
                "No API key configured. Set one via:\n"
                "  export AGENT_KNOTS_API_KEY=<your-key>\n"
                "  export AGENT_KNOTS_MODEL=<model-id>\n"
                "Or add to ~/.agent-knots/settings.yaml:\n"
                "  agent:\n"
                "    api_key: <your-key>\n"
                "    default_model: openai/gpt-4o-mini"
            )

        session_id = uuid.uuid4().hex[:12]
        from agent_knots.names import generate_name
        session_name = generate_name({s.name for s in self._sessions.values()})

        task_context = self._resolve_task_context(session_id, task_id, advisory)
        workspace_context = self._build_workspace_context(project_id)
        full_prompt = self._build_full_prompt(system_prompt, task_context, workspace_context, mode, task_id)
        resolved_working_dir = self._resolve_working_dir(working_dir, project_id, session_id)

        # Branch before anything binds to the working tree — the sandbox
        # and the shell/editor tools below all take resolved_working_dir
        # as their cwd, and checking out afterwards would swap files
        # underneath an agent that had already started.
        branch_result = await self._ensure_branch(
            resolved_working_dir, project_id, task_id, session_id, advisory,
        )

        # Resolved once, synchronously, so any unavailable credential is
        # visible in the system prompt from the agent's first turn
        # rather than only surfacing when a shell command using it first
        # fails. cred_env (if any) is then handed to the shell tool below
        # as a re-resolving provider, so unlocking the vault later still
        # takes effect on the next command.
        cred_env, cred_problems = self._resolve_credential_env(task_id, session_id)
        if cred_problems:
            full_prompt = full_prompt + "\n\nUnavailable credentials: " + "; ".join(cred_problems)

        # Custom (shell-command) tools are bound to resolved_working_dir here
        # since, unlike the built-in shell/editor tools below, they have no
        # separate sandboxed-swap step.
        all_tools = self._build_tools(tools, resolved_working_dir, session_id, project_id)
        model_instance = self._build_model_instance(provider)

        # background_pids is created here (before the Session below exists)
        # and handed to both the shell tool closure and the Session itself
        # as the same list object, so a background=true shell command's pid
        # lands somewhere SessionManager.stop() can find and clean up later
        # — without this, a dev server an agent starts in the background
        # would outlive the session indefinitely.
        ws_sandbox, background_pids = self._maybe_create_sandbox(resolved_working_dir)
        all_tools = self._swap_sandboxed_tools(
            all_tools, ws_sandbox, session_id, background_pids,
            env_provider=cred_env.get_env if cred_env else None,
        )

        # Create the agent with mode-aware intervention handler.
        from agent_knots.intervention import ModeInterventionHandler

        intervention_handler = ModeInterventionHandler(
            get_mode=lambda: session.mode,
            get_allowed_tools=lambda: session.allowed_tools,
        )

        agent = Agent(
            model=model_instance,
            tools=all_tools,
            system_prompt=full_prompt,
            sandbox=None,
            agent_id=session_id,
            interventions=[intervention_handler],
        )

        session = Session(
            id=session_id,
            name=session_name,
            mode=mode,
            task_id=task_id,
            project_id=project_id,
            working_dir=resolved_working_dir,
            model=provider.model,
            branch=branch_result.name,
            branch_created=branch_result.created,
            branch_base=branch_result.base,
            advisory=advisory,
            allowed_tools=set(allowed_tools) if allowed_tools is not None else None,
            role=role,
            _agent=agent,
            _background_pids=background_pids,
            _base_prompt=system_prompt,
            _task_context=task_context,
            _workspace_context=workspace_context,
        )
        self._sessions[session_id] = session

        if branch_result.name and resolved_working_dir and not advisory:
            self._repo_writers[resolved_working_dir] = session_id
        self._announce_branch(session, branch_result)
        self._announce_credential_problems(session, cred_problems)

        self._register_hooks(agent, session, task_id)

        runtime_type = self._resolve_runtime_type(runtime_override, project_id)

        # A session started with no explicit prompt but a bound task still
        # needs its first turn kicked off — the task's full context is
        # already in full_prompt above, but both runtimes only start the
        # agent when task_description is non-empty, so an "agent" mode
        # session attached to a task via a bare "Start" button (prompt
        # always "") would otherwise sit idle forever, looking dead until
        # something else (e.g. assume/relinquish + a typed message)
        # happened to trigger a turn.
        initial_message = task_description or ("Begin working on the assigned task." if task_id else "")

        from agent_knots.session.runtime import create_runtime
        runtime = create_runtime(self, runtime_type=runtime_type)
        await runtime.start(session, {
            "model": provider.model,
            "api_key": provider.api_key,
            "base_url": provider.base_url or "",
            "workspace_dir": resolved_working_dir or "",
            "system_prompt": full_prompt,
            "task_description": initial_message,
        })

        return session

    async def stop(self, session_id: str) -> None:
        """Stop a running session."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        await session.cancel()

        # Background=true commands (dev servers, watchers) are meant to
        # outlive any single turn, but not the session itself — clean
        # them up now or they'd leak forever once the session is gone.
        if session._background_pids:
            from agent_knots.sandbox_tools import kill_background_process
            for pid in session._background_pids:
                kill_background_process(pid)

        await self._teardown_branch(session)
        self._record_wastebin(session)

        session._broadcast(Event(
            type=EventType.ENDED,
            session_id=session_id,
            message="Session stopped.",
        ))

        if session.tokens_used > 0:
            from agent_knots.config import usage_file
            from agent_knots.usage import UsageEntry, record

            record(usage_file(), UsageEntry(
                session_id=session.id,
                model=session.model,
                task_id=session.task_id,
                tokens=session.tokens_used,
                cost_usd=session.cost_usd,
            ))

    def _record_wastebin(self, session: Session) -> None:
        """Leave a tombstone for this session — otherwise stop() is the
        last anyone ever hears of it: sessions aren't persisted, so
        without this there'd be no history and no way to find (let
        alone clean up) whatever branch or workdir it left behind.

        Every session gets one, even a completely trivial one with no
        branch and nothing written — that's what makes this double as
        session history, not just a cleanup queue. Never lets bookkeeping
        block a session from actually stopping.
        """
        try:
            from agent_knots.config import session_workdir, wastebin_dir
            from agent_knots.config import tasks_dir as _tasks_dir
            from agent_knots.task.store import TaskStore
            from agent_knots.wastebin import WastebinEntry, WastebinStore

            task_title = ""
            if session.task_id:
                task = TaskStore(_tasks_dir()).get(session.task_id)
                if task:
                    task_title = task.title

            is_auto_workdir = bool(
                session.working_dir
                and session.working_dir == str(session_workdir(session.id)),
            )

            from agent_knots.events import serialize_event

            WastebinStore(wastebin_dir()).add(WastebinEntry(
                session_id=session.id,
                name=session.name,
                task_id=session.task_id,
                task_title=task_title,
                project_id=session.project_id,
                branch=session.branch,
                branch_base=session.branch_base,
                working_dir=session.working_dir or "",
                is_auto_workdir=is_auto_workdir,
                role=session.role,
                advisory=session.advisory,
                mode=session.mode,
                model=session.model,
                tokens_used=session.tokens_used,
                cost_usd=session.cost_usd,
                started_at=session.started_at,
                history=[serialize_event(e) for e in session._history],
            ))
        except Exception:
            pass

    async def _teardown_branch(self, session: Session) -> None:
        """Release the session's hold on the repo, deleting its branch
        only if the session left nothing behind.

        A branch with commits is always kept — that's the work. An empty
        one is noise from a session that started and did nothing, so it
        goes. Never raises: teardown failing must not stop a session
        being stopped.
        """
        if session.working_dir:
            if self._repo_writers.get(session.working_dir) == session.id:
                del self._repo_writers[session.working_dir]

        if not (session.branch_created and session.working_dir and session.branch_base):
            return
        try:
            deleted = await delete_branch_if_empty_async(
                Path(session.working_dir), session.branch, session.branch_base,
            )
            if deleted:
                message = f"Removed empty branch {session.branch}."
                # Reflect reality on the Session object itself, not just
                # the broadcast event — anything reading session.branch
                # after teardown (e.g. the wastebin tombstone written
                # right after this) must see that it's gone, not a name
                # that no longer exists on disk.
                session.branch = None
                session._broadcast(Event(
                    type=EventType.STATE_CHANGE,
                    session_id=session.id,
                    message=message,
                    data={"branch": None},
                ))
        except Exception:
            pass

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

        session._broadcast(Event(
            type=EventType.USER,
            session_id=session_id,
            message=message,
        ))

        session._task = asyncio.create_task(
            self._run_agent(session, session._agent, message)
        )

    async def interrupt(self, session_id: str) -> None:
        """Cancel the agent's current turn only.

        Unlike stop(), the session is not removed — it stays in
        self._sessions so a follow-up send() can pick the conversation
        back up. A no-op if the agent isn't currently running.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} not found")
        if not session.running:
            return
        await session.cancel(end_session=False)

    async def set_mode(self, session_id: str, mode: str) -> None:
        """Change the agent's raw mode field.

        Tools run in every mode — 'reviewer'/'security' are the only ones
        an intervention handler denies tool calls in (see
        intervention.py). 'agent' vs 'assistant' doesn't gate tool
        permission at all; it's read by set_autonomous()/the web UI as
        "is this task-attached session currently self-directing or
        paused for conversation" — see set_autonomous() below, which is
        almost always what you want to call instead of this for that
        agent/assistant toggle, since it also handles interrupting the
        current turn and resuming the task.

        Also rebuilds the system prompt so the agent's own instructions
        match its current mode — without this the agent still thinks it's
        autonomous (or interactive) based on whatever mode the session
        was created in, regardless of later toggles.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} not found")

        session.mode = mode

        # Rebuild the system prompt from stored components with the new mode.
        if session._agent is not None:
            new_prompt = _build_system_prompt(
                session._base_prompt, session._task_context, session._workspace_context, mode,
            )
            if session.task_id:
                from agent_knots.session.features import inject_memory
                memory_block = inject_memory(session.task_id)
                if memory_block:
                    new_prompt = new_prompt + "\n\n" + memory_block
            session._agent.system_prompt = new_prompt

        session._broadcast(Event(
            type=EventType.STATE_CHANGE,
            session_id=session_id,
            message=f"Mode changed to {mode}",
        ))

    async def set_autonomous(self, session_id: str, on: bool) -> None:
        """Toggle a task-attached session between autonomous (self-
        directed from the task) and paused (interactive, back-and-forth
        — still fully tool-capable, just not self-continuing) work.

        Turning it off interrupts whatever's currently running
        immediately — the equivalent of "hold up" — and stops it from
        self-continuing until turned back on. Turning it back on nudges
        the agent to resume the task, incorporating anything discussed
        while paused. Sending a message while autonomous is still on is
        itself a "hold up": the web UI calls this with on=False before
        sending, rather than requiring an explicit toggle first.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} not found")

        if on:
            await self.set_mode(session_id, "agent")
            if session.task_id:
                await self.send(
                    session_id,
                    "Resume working on the task — pick up where you left "
                    "off, taking into account anything discussed above.",
                )
        else:
            await self.interrupt(session_id)
            await self.set_mode(session_id, "assistant")

    def checkpoint(self, session_id: str, label: str) -> None:
        """Mark a checkpoint in the thread. No real snapshot is taken —
        this only broadcasts a marker event for the UI's "revert to
        here" affordance. Real checkpoint/revert (conversation-history +
        worktree snapshotting) is real, larger, future work. A prior
        save_checkpoint/load_checkpoint implementation was removed as
        orphaned dead code rather than wired up.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} not found")
        session._broadcast(Event(
            type=EventType.CHECKPOINT,
            session_id=session_id,
            message=label,
        ))

    def revert(self, session_id: str, label: str) -> None:
        """"Revert to" a checkpoint — logs the action, does not actually
        roll back any state. See checkpoint()'s docstring."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} not found")
        session._broadcast(Event(
            type=EventType.STATE_CHANGE,
            session_id=session_id,
            message=f"Workspace reverted to checkpoint {label!r} (not implemented — no real snapshot exists yet).",
        ))

    # ── internals ─────────────────────────────────────────────────────────

    async def _run_agent(
        self,
        session: Session,
        agent: Agent,
        prompt: str,
    ) -> None:
        """Run the agent with a prompt, broadcasting events to subscribers."""
        finished = False
        try:
            session._broadcast(Event(
                type=EventType.STATE_CHANGE,
                session_id=session.id,
                message="Agent started.",
            ))

            chunk_state: dict[str, Any] = {}

            async for chunk in agent.stream_async(prompt):
                if session._cancel_kind is not CancelKind.NONE:
                    break

                result = self._chunk_to_event(session.id, chunk, chunk_state)
                if result is not None:
                    for event in (result if isinstance(result, list) else [result]):
                        session._broadcast(event)

            if session._cancel_kind is CancelKind.NONE:
                finished = True
                # A turn finishing is NOT the session ending — send() can
                # still start another turn afterward (multi-turn chat).
                # EventType.ENDED is reserved for stop()/cancellation, so
                # the frontend's composer only locks into replay mode on
                # a real end, not after every response.
                session._broadcast(Event(
                    type=EventType.STATE_CHANGE,
                    session_id=session.id,
                    message="Agent finished.",
                ))

        except asyncio.CancelledError:
            if not finished:
                if session._cancel_kind is CancelKind.INTERRUPT:
                    session._broadcast(Event(
                        type=EventType.STATE_CHANGE,
                        session_id=session.id,
                        message="Cancelled — send another message to continue.",
                    ))
                else:
                    session._broadcast(Event(
                        type=EventType.ENDED,
                        session_id=session.id,
                        message="Agent cancelled.",
                    ))
        except Exception as exc:
            session._broadcast(Event(
                type=EventType.ERROR,
                session_id=session.id,
                error=str(exc),
                message=f"Agent error: {exc}",
            ))
        finally:
            session._cancel_kind = CancelKind.NONE

    @staticmethod
    def _chunk_to_event(
        session_id: str, chunk: Any, _state: dict[str, Any] | None = None
    ) -> Event | list[Event] | None:
        """Translate a Strands stream chunk into an agent-knots Event (or,
        when a single delta straddles a <think>/</think> boundary, two).

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

                    # <think>...</think> markers can arrive split across
                    # multiple deltas, and a single delta can itself
                    # straddle the boundary (e.g. "...done thinking</think>
                    # Hello!" all in one fragment) — classifying that whole
                    # fragment as one type either leaks real response text
                    # into a THINKING bubble or vice versa. Split at every
                    # tag boundary found in this fragment instead, carrying
                    # in_think across calls for boundaries split across
                    # separate deltas.
                    in_think = _state.get('in_think', False)
                    segments: list[tuple[bool, str]] = []
                    remaining = new_text
                    cur = in_think
                    while remaining:
                        tag = '</think>' if cur else '<think>'
                        idx = remaining.find(tag)
                        if idx == -1:
                            segments.append((cur, remaining))
                            remaining = ''
                        else:
                            before = remaining[:idx]
                            if before:
                                segments.append((cur, before))
                            cur = not cur
                            remaining = remaining[idx + len(tag):]
                    _state['in_think'] = cur

                    events = [
                        Event(
                            type=EventType.THINKING if is_think else EventType.MESSAGE,
                            session_id=session_id,
                            message=text,
                            timestamp=now,
                        )
                        for is_think, text in segments if text
                    ]
                    if events:
                        _state['streamed_any'] = True
                    if not events:
                        return None
                    return events if len(events) > 1 else events[0]
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
                        # Strands' own ToolResult.status ("success"/"error")
                        # is a tool-agnostic success signal — works for the
                        # shell tool's exit_code as much as the editor,
                        # calculator, or any task tool, none of which have
                        # a real exit code. Previously this went unset
                        # entirely, so the frontend had no way to tell a
                        # failed tool call from a successful one and
                        # rendered every result identically.
                        failed = tr.get('status') == 'error'
                        return Event(
                            type=EventType.TOOL_RESULT,
                            session_id=session_id,
                            message=result_text,
                            data=tr,
                            tool_result=ToolResult(
                                tool_call_id=tr.get('toolUseId', ''),
                                stdout='' if failed else result_text,
                                stderr=result_text if failed else '',
                                exit_code=1 if failed else 0,
                                error=result_text if failed else '',
                            ),
                            timestamp=now,
                        )
                # Regular content blocks — extract text.
                text = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
            else:
                text = str(content)

            # This chunk's text is the fully-assembled turn — the same
            # text the 'data'+'delta' branch above already streamed
            # piece by piece. Re-emitting it here duplicated every
            # response ("Hello!... " appearing once streamed in and then
            # again in full). Only emit it if nothing was actually
            # streamed this turn (a non-streaming provider that only
            # ever sends this one final chunk).
            if _state.get('streamed_any'):
                return None

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

        # Result — final completion. No event here: _run_agent already
        # broadcasts its own "Agent finished." once the stream loop ends
        # without cancellation, and this chunk always precedes that —
        # emitting one here too was producing the message twice per turn.
        if 'result' in chunk:
            return None

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

    # ── start() helpers ──────────────────────────────────────────────────
    # Extracted from start(), which used to do all of this inline as one
    # ~10-job function (task lookup/assignment, prompt assembly, working-
    # dir resolution, tool assembly, model construction, sandboxing,
    # runtime resolution). Each helper below is a self-contained,
    # pure(-ish) step with no dependency on Agent/Session construction
    # order — that part stays inline in start() itself, since the
    # intervention handler's `lambda: session.mode` relies on Python's
    # late-binding closures to read `session` before it's actually
    # assigned (Agent must be built first, since Session's constructor
    # takes the already-built Agent as `_agent`), which is exactly the
    # kind of ordering-sensitive code not worth pulling into a helper
    # that could accidentally reorder it.

    # Statuses a writer session claiming a task auto-transitions out of.
    # Not just "open" — a freshly created task defaults to 'draft'
    # (task/models.py), so restricting this to 'open' meant a task
    # someone started an agent on straight from draft (the common case)
    # never visibly showed as being worked at all. blocked is included
    # too: an agent resuming after answering a blocker is very much
    # back to in_progress, not still blocked.
    _AUTO_START_STATUSES = ("draft", "open", "planned", "blocked")

    @classmethod
    def _claim_task(cls, store: Any, task: Any, session_id: str) -> None:
        """A writer session taking on a task — starting with it, or
        adopting it mid-session via maybe_adopt_task — always assigns
        it and moves it to in_progress unless it's already past that
        point (in_progress/review/done/abandoned)."""
        store.assign(task.id, session_id)
        if task.status.value in cls._AUTO_START_STATUSES:
            from agent_knots.task.models import TaskStatus
            store.set_status(task.id, TaskStatus("in_progress"))

    def _resolve_task_context(
        self, session_id: str, task_id: str | None, advisory: bool = False,
    ) -> str:
        """Fetch the task's prompt context and, if found, claim it for
        this session — a task should never sit assigned-to-a-session but
        still sitting in a not-yet-started status.

        An advisory session skips this: assign() is last-writer-wins, so
        an advisory reviewer claiming assigned_to would knock the actual
        writer off the task the moment it starts, and it has no business
        forcing a task into 'in_progress' just by observing it.
        """
        if not task_id:
            return ""
        from agent_knots.task.store import TaskStore
        from agent_knots.config import tasks_dir as _tasks_dir

        store = TaskStore(_tasks_dir())
        task = store.get(task_id)
        if not task:
            return ""
        if not advisory:
            self._claim_task(store, task, session_id)
        return _build_task_prompt(task)

    def maybe_adopt_task(self, session_id: str, task_id: str) -> None:
        """A session started with no task_id adopts the first task it
        creates or logs progress/status on — so the goal rail (and Task
        Detail's "who's working on this") reflect a task an agent picks
        up mid-session the same as one it was started with.

        Only fires once: a session already tied to a task keeps that
        task even if it later touches a second one, rather than the
        goal rail silently swapping out from under whoever's watching.
        Advisory sessions are excluded for the same reason
        _resolve_task_context excludes them from assign() — an advisory
        reviewer touching a task has no business claiming it.
        """
        session = self._sessions.get(session_id)
        if session is None or session.task_id or session.advisory:
            return
        session.task_id = task_id
        from agent_knots.task.store import TaskStore
        from agent_knots.config import tasks_dir as _tasks_dir

        store = TaskStore(_tasks_dir())
        task = store.get(task_id)
        if task:
            self._claim_task(store, task, session_id)

    @staticmethod
    def _build_workspace_context(project_id: str | None) -> str:
        """Fetch the workspace's prompt context, if project_id names one.

        Without this, a workspace-attached session had no way to know
        it was in a workspace at all — not its name, not its
        description, nothing — beyond whatever it could infer from
        files already sitting in its own working directory.
        """
        if not project_id:
            return ""
        from agent_knots.project.store import ProjectStore
        from agent_knots.config import projects_dir as _projects_dir

        project = ProjectStore(_projects_dir()).get(project_id)
        if not project:
            return ""
        return _build_workspace_prompt(project)

    @staticmethod
    def _build_full_prompt(
        system_prompt: str, task_context: str, workspace_context: str, mode: str, task_id: str | None,
    ) -> str:
        """Assemble the system prompt, then inject cross-session memory
        from the task's own prior progress log, if there is one."""
        full_prompt = _build_system_prompt(system_prompt, task_context, workspace_context, mode)
        if task_id:
            from agent_knots.session.features import inject_memory
            memory_block = inject_memory(task_id)
            if memory_block:
                full_prompt = full_prompt + "\n\n" + memory_block
        return full_prompt

    async def _ensure_branch(
        self,
        working_dir: str | None,
        project_id: str | None,
        task_id: str | None,
        session_id: str,
        advisory: bool,
    ) -> BranchResult:
        """Put this session on its own git branch, if that's possible here.

        Every "no" is a skip carrying a reason, never an exception — a
        git problem is not a reason to refuse to start an agent.

        Advisory sessions never branch: they share the writer's working
        tree, and since `git checkout` is process-global, branching would
        move the writer's files too.
        """
        if advisory:
            return BranchResult(skipped_reason="advisory session shares the writer's branch")
        if not working_dir:
            return BranchResult(skipped_reason="no working directory")

        # A second writer in the same repo would fight the first over
        # HEAD. Leave it on whatever the first writer checked out.
        owner = self._repo_writers.get(working_dir)
        if owner is not None and owner in self._sessions:
            return BranchResult(
                skipped_reason=f"repo already checked out by session {owner}",
            )

        repo = Path(working_dir)
        # Checked here as well as inside ensure_session_branch so the
        # skip reason is the accurate one — resolving a base branch in a
        # non-repo also fails, but "no base branch" would misdescribe why.
        if not is_repo(repo):
            return BranchResult(skipped_reason="not a git repository")

        base = self._resolve_base_branch(repo, project_id)
        if not base:
            return BranchResult(skipped_reason="no base branch (detached HEAD?)")

        task_title = ""
        if task_id:
            from agent_knots.config import tasks_dir as _tasks_dir
            from agent_knots.task.store import TaskStore

            task = TaskStore(_tasks_dir()).get(task_id)
            if task:
                task_title = task.title

        name = session_branch_name(task_id, task_title, session_id)
        return await ensure_session_branch_async(repo, name, base)

    @staticmethod
    def _resolve_base_branch(repo: Path, project_id: str | None) -> str:
        """Workspace's configured default_branch > whatever is checked
        out > "" (caller treats as unbranchable)."""
        if project_id:
            from agent_knots.config import projects_dir as _projects_dir
            from agent_knots.project.store import ProjectStore

            proj = ProjectStore(_projects_dir()).get(project_id)
            if proj and proj.default_branch and branch_exists(repo, proj.default_branch):
                return proj.default_branch
        return current_branch(repo) or ""

    def _announce_branch(self, session: Session, result: BranchResult) -> None:
        """Surface the branch outcome to the UI and, when there's a task,
        to its progress log.

        The progress entry is the only durable record of the branch:
        sessions live in memory and die with the process, but task YAML
        persists, so this is what tells you later which branch a task's
        work went to.
        """
        if result.name:
            message = f"Working on branch {result.name} (from {result.base})."
        else:
            message = f"No session branch — {result.skipped_reason}."

        session._broadcast(Event(
            type=EventType.STATE_CHANGE,
            session_id=session.id,
            message=message,
            data={"branch": result.name, "branch_base": result.base},
        ))

        if not (session.task_id and result.name):
            return
        try:
            from agent_knots.config import tasks_dir as _tasks_dir
            from agent_knots.task.models import ProgressEntry
            from agent_knots.task.store import TaskStore

            TaskStore(_tasks_dir()).log_progress(session.task_id, ProgressEntry(
                entry=f"Branch {result.name} created from {result.base}."
                      if result.created else f"Resumed on branch {result.name}.",
                caller=session.id,
            ))
        except Exception:
            # Never let progress bookkeeping stop a session starting.
            pass

    def _resolve_credential_env(
        self, task_id: str | None, session_id: str,
    ) -> tuple[_SessionCredentialEnv | None, list[str]]:
        """Resolve the task's required_credentials into env vars, if
        there's a vault and a task that names any.

        Returns (None, []) whenever there's nothing to inject — no
        vault configured, no task, or a task with no
        required_credentials — so the caller can skip wiring an
        env_provider into the shell tool at all rather than plumbing
        through an always-empty one.
        """
        if not (self.vault and task_id):
            return None, []
        from agent_knots.config import tasks_dir as _tasks_dir
        from agent_knots.task.store import TaskStore

        task = TaskStore(_tasks_dir()).get(task_id)
        if not task or not task.required_credentials:
            return None, []

        cred_env = _SessionCredentialEnv(self.vault, task.required_credentials, caller=session_id)
        _, problems = cred_env.resolve()
        return cred_env, problems

    def _announce_credential_problems(self, session: Session, problems: list[str]) -> None:
        """Surface missing/locked credentials the same way branch
        outcomes are surfaced: a UI event plus a task progress entry, so
        the gap is visible even after the session that hit it ends."""
        if not problems:
            return
        message = "Unavailable credentials: " + "; ".join(problems)
        session._broadcast(Event(
            type=EventType.STATE_CHANGE,
            session_id=session.id,
            message=message,
        ))
        if not session.task_id:
            return
        try:
            from agent_knots.config import tasks_dir as _tasks_dir
            from agent_knots.task.models import ProgressEntry
            from agent_knots.task.store import TaskStore

            TaskStore(_tasks_dir()).log_progress(session.task_id, ProgressEntry(
                entry=message, caller=session.id,
            ))
        except Exception:
            pass

    @staticmethod
    def _resolve_working_dir(
        working_dir: str | None, project_id: str | None, session_id: str,
    ) -> str:
        """explicit > workspace repo > a fresh per-session workdir.

        Always returns a real, existing directory — never None/empty.
        A session with no explicit working_dir and no project attached
        used to fall through to no working directory at all, which
        meant no sandbox, which meant its shell/editor tools fell back
        to strands_tools' raw, unbounded versions operating on wherever
        the agent-knots server process itself happened to be running
        from (confirmed live: this wrote a file straight into this
        project's own repo during testing). config.session_workdir()
        gives every session somewhere real and contained instead.
        """
        if working_dir:
            return working_dir
        if project_id:
            from agent_knots.project.store import ProjectStore
            from agent_knots.config import projects_dir as _projects_dir

            proj = ProjectStore(_projects_dir()).get(project_id)
            if proj and proj.repository:
                return proj.repository

        from agent_knots.config import session_workdir

        return str(session_workdir(session_id))

    def _build_tools(
        self, tools: list[Any] | None, resolved_working_dir: str | None, session_id: str,
        project_id: str | None = None,
    ) -> list[Any]:
        """Default tools + enabled custom tools from the registry, plus
        the delegate_task tool for multi-agent delegation. Must run
        before the Agent is constructed — Strands reads the tools list
        at construction time, so appending afterward has no effect."""
        from agent_knots.tools.defaults import auto_approve_tools
        from agent_knots.tools.registry import ToolRegistry

        auto_approve_tools()
        registry = ToolRegistry()
        all_tools = list(tools or []) + registry.list_enabled(cwd=resolved_working_dir)

        # create_task/read_task/list_tasks/update_task_status/log_progress,
        # if enabled, get swapped for session-aware versions — same
        # by-name-swap technique as the sandboxed shell/editor tools
        # below. Handles workspace scoping, auto-stop/role-trigger side
        # effects on status changes, and task adoption for a taskless
        # session — see make_session_aware_task_tools's docstring.
        from agent_knots.task.tools import make_session_aware_task_tools
        session_aware = {
            t.__name__: t
            for t in make_session_aware_task_tools(self, session_id, project_id or "")
        }
        all_tools = [session_aware.get(getattr(t, "__name__", ""), t) for t in all_tools]

        from agent_knots.session.features import make_delegate_tool, make_ask_user_tool
        all_tools.append(make_delegate_tool(self, session_id))
        all_tools.append(make_ask_user_tool(self, session_id))
        return all_tools

    @staticmethod
    def _build_model_instance(provider: Any) -> Any:
        """Strands expects a model instance, not a config dict — for
        OpenAI-compatible providers, that's OpenAIModel with client_args."""
        from strands.models.openai import OpenAIModel

        client_args: dict[str, Any] = {}
        if provider.api_key:
            client_args["api_key"] = provider.api_key
        if provider.base_url:
            client_args["base_url"] = provider.base_url

        return OpenAIModel(model_id=provider.model, client_args=client_args or None)

    @staticmethod
    def _maybe_create_sandbox(resolved_working_dir: str | None) -> tuple[Any, list[int]]:
        """Returns (sandbox-or-None, a fresh background_pids list) — the
        list is always created here (even with no sandbox) since the
        caller hands it to both the shell tool closure and the Session
        as the same object regardless."""
        background_pids: list[int] = []
        if not resolved_working_dir:
            return None, background_pids
        from agent_knots.isolation import create_sandbox
        return create_sandbox(str(resolved_working_dir)), background_pids

    @staticmethod
    def _swap_sandboxed_tools(
        all_tools: list[Any], ws_sandbox: Any, session_id: str, background_pids: list[int],
        env_provider: Any = None,
    ) -> list[Any]:
        """Swap in sandboxed shell/editor tools if we have a workspace."""
        if not (ws_sandbox and ws_sandbox.exists):
            return all_tools
        from agent_knots.sandbox_tools import make_sandboxed_shell, make_sandboxed_editor

        ws = ws_sandbox.workspace_dir
        sb_shell = make_sandboxed_shell(
            ws, max_output=ws_sandbox.max_output,
            session_id=session_id, background_pids=background_pids,
            env_provider=env_provider,
        )
        sb_editor = make_sandboxed_editor(ws, max_file_size=ws_sandbox.max_file_size)
        return [
            sb_shell if getattr(t, '__name__', '') == 'shell'
            else sb_editor if getattr(t, '__name__', '') == 'editor'
            else t
            for t in all_tools
        ]

    @staticmethod
    def _register_hooks(agent: Agent, session: Session, task_id: str | None) -> None:
        """Cost tracking + auto progress logging, plus the steering hook
        for criteria validation if this session is task-attached."""
        from agent_knots.hooks import register_session_hooks
        register_session_hooks(agent, session)

        if task_id:
            from agent_knots.session.features import register_steering_hook
            register_steering_hook(agent, task_id, session)

    @staticmethod
    def _resolve_runtime_type(runtime_override: str, project_id: str | None) -> str:
        """explicit override > workspace setting > global setting."""
        if runtime_override:
            return runtime_override
        if project_id:
            from agent_knots.project.store import ProjectStore
            from agent_knots.config import projects_dir as _projects_dir

            proj = ProjectStore(_projects_dir()).get(project_id)
            if proj and proj.runtime:
                return proj.runtime
        from agent_knots.session.runtime import get_runtime_type
        return get_runtime_type()


def _parse_tool_input(raw: str) -> dict:
    """Parse a tool input JSON string, returning empty dict on failure."""
    import json as _json
    try:
        return _json.loads(raw) if raw and raw != '{}' else {}
    except (_json.JSONDecodeError, TypeError):
        return {}


def _build_task_prompt(task: Any) -> str:
    """Build a task context block for the system prompt."""
    from agent_knots.task.models import Task as TaskModel
    t: TaskModel = task
    parts = [
        "## Current Task",
        f"Task ID: {t.id}",
        f"Title: {t.title}",
        f"Status: {t.status.value}",
        f"Priority: {t.priority.value}",
    ]
    if t.review_gate.value != "none":
        parts.append(
            "\nThis task requires a review step: move it to 'review' status "
            "first, not straight to 'done' — attempting 'done' from any "
            "other status will be refused."
        )
    if t.description:
        parts.append(f"\nDescription:\n{t.description}")
    if t.acceptance_criteria:
        met = set(t.criteria_met)
        parts.append("\nAcceptance Criteria:")
        for c in t.acceptance_criteria:
            parts.append(f"  {'✓' if c in met else '○'} {c}")
        if t.unmet_criteria():
            parts.append(
                "\nEvery criterion above must be marked met via mark_criterion_met "
                "(only once you've actually verified it) before update_task_status "
                "or log_progress can move this task to 'done' — the tool call will "
                "be refused otherwise."
            )
    if t.steps:
        parts.append("\nSteps:")
        for s in t.steps:
            icon = "✓" if s.status.value == "done" else "○" if s.status.value == "draft" else "●"
            parts.append(f"  {icon} {s.title} [{s.status.value}]")
    if t.progress:
        parts.append(f"\nProgress log ({len(t.progress)} entries, most recent last):")
        for p in t.progress[-5:]:
            parts.append(f"  [{p.status.value}] {p.entry}")
    parts.append("\nUse the task tools (create_task, read_task, log_progress, update_task_status, mark_criterion_met, add_step, list_tasks) to manage this task. Log progress after every meaningful action.")
    return "\n".join(parts)


def _build_workspace_prompt(project: Any) -> str:
    """Build a workspace context block for the system prompt."""
    parts = [
        "## Workspace",
        f"Workspace ID: {project.id}",
        f"Name: {project.name}",
    ]
    if project.description:
        parts.append(f"Description: {project.description}")
    if project.repository:
        parts.append(f"Repository: {project.repository}")
    parts.append(
        "\nAny task you create with create_task is created in this "
        "workspace automatically — you don't need to (and can't) put it "
        "in a different one from this session."
    )
    return "\n".join(parts)


def _build_system_prompt(base_prompt: str, task_context: str, workspace_context: str, mode: str) -> str:
    """Assemble the full system prompt."""
    parts = []

    if base_prompt:
        parts.append(base_prompt)

    if workspace_context:
        parts.append(workspace_context)

    if mode == "agent":
        parts.append("You are an autonomous coding agent. You have tools for reading/writing files, running shell commands, editing code, and managing tasks. Work through tasks systematically. Log progress after every meaningful action using the task tools provided.")
    elif mode == "assistant":
        parts.append("You are a coding assistant working interactively with a user. You have tools for reading/writing files, running shell commands, editing code, and managing tasks. Ask clarifying questions when needed. Log progress using the task tools provided.")
    elif mode == "reviewer":
        parts.append("You are a code reviewer. Focus on finding issues, suggesting improvements, and verifying correctness. Do not make changes unless asked.")
    elif mode == "security":
        parts.append("You are a security auditor. Focus on finding vulnerabilities, unsafe patterns, and security anti-patterns. Do not make changes unless asked.")

    if mode in ("agent", "assistant"):
        parts.append(
            "When starting a dev server or any other long-running process the user needs to keep using "
            "(npm run dev, vite, next dev, etc.), call the shell tool with background=true — it starts "
            "the process detached and returns immediately with its pid and a log file, instead of being "
            "killed once the tool call's timeout is reached (which a plain foreground shell call always "
            "is, even though the command looked like it started fine). Do not try to hand-roll this "
            "yourself with `nohup ... &`; use background=true. "
            "Also bind dev servers to all network interfaces (e.g. add `--host` / `--host 0.0.0.0`) "
            "instead of leaving them on the tool's default host — on many systems 'localhost' resolves "
            "to the IPv6 loopback only, so a server bound to the default can be running fine yet "
            "unreachable from the user's browser at http://localhost:<port> or http://127.0.0.1:<port>."
        )

    if task_context:
        parts.append(task_context)

    return "\n\n".join(parts)
