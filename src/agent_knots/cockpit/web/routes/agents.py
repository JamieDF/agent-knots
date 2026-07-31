"""Agent/session lifecycle routes: list, SSE events, detail, file
preview, real terminal, mode control, and session creation."""

import asyncio
import json
import os
import signal
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

try:
    import pty
    import fcntl
    import struct
    import termios
    HAS_PTY = True
except ImportError:  # Windows has no pty module
    HAS_PTY = False

from agent_knots.cockpit.web.auth import Auth, COOKIE_NAME, verify_token
from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import AutonomousRequest, CheckpointRequest, CreateSessionRequest
from agent_knots.config import tasks_dir, policies_file, usage_file
from agent_knots.events import serialize_event
from agent_knots import provider as provider_module
from agent_knots import usage as usage_module
from agent_knots.policies.store import PolicyStore
from agent_knots.session.manager import SessionManager
from agent_knots.task.store import TaskStore


def _summarize_last_activity(session) -> str:
    """A short, human-readable snapshot of the most recent thing this
    session did — the Dashboard only polls the agent list (not full
    SSE), so its cards had nothing to show beyond a static
    "working…"/"idle" word with zero actual content.

    Walks _history backward: a run of consecutive message/thinking
    deltas gets joined into one readable trailing excerpt (mirrors
    AgentThread's reduceEvent merge, just enough of it for a summary);
    otherwise the most recent tool call, described by name.
    """
    history = session._history
    if not history:
        return ""

    last = history[-1]
    if last.type.value in ("message", "thinking"):
        parts: list[str] = []
        for ev in reversed(history):
            if ev.type is not last.type:
                break
            parts.append(ev.message or "")
        text = "".join(reversed(parts)).strip()
        if text:
            prefix = "Thinking: " if last.type.value == "thinking" else ""
            return prefix + (text[:140] + "…" if len(text) > 140 else text)

    for ev in reversed(history):
        if ev.type.value == "tool_call" and ev.tool_call:
            name = ev.tool_call.name
            args = ev.tool_call.args or {}
            # Every session gets a sandboxed working dir now (see
            # SessionManager._resolve_working_dir), so the swapped-in
            # shell_tool/editor_tool (sandbox_tools.py) is always what's
            # actually in play, not the richer strands-native
            # 'shell'/'editor' tools this used to check for — which no
            # live tool call ever matches anymore.
            if name == "shell_tool":
                cmd = args.get("command", "")
                return f"Running: {cmd}"[:140] if cmd else "Running a shell command"
            if name == "editor_tool":
                path = args.get("path", "")
                return f"Editing {path}" if path else "Using the editor"
            return f"Using {name}"
        if ev.type.value == "state_change" and ev.message:
            return ev.message

    return ""


def _agent_to_response(session) -> dict:
    pq = session._pending_question
    pending = None
    if pq and pq.get("event") and not pq["event"].is_set():
        pending = {
            "question": pq.get("question", ""),
            "options": pq.get("options"),
        }
    return {
        "id": session.id,
        "mode": session.mode,
        "task_id": session.task_id,
        "project_id": session.project_id,
        "tokens_used": session.tokens_used,
        "cost_usd": session.cost_usd,
        "running": session.running,
        "model": session.model,
        "started_at": session.started_at,
        "pending_question": pending,
        "branch": session.branch,
        "advisory": session.advisory,
        "role": session.role,
        "last_activity": _summarize_last_activity(session),
    }


def _wastebin_entry_to_agent_response(entry) -> dict:
    """Same shape as _agent_to_response, for a session that's already
    stopped — reopening it (from Task Detail's history, say) shouldn't
    404 just because it isn't live anymore. running is always False and
    there's never a pending question (nothing left to answer)."""
    return {
        "id": entry.session_id,
        "mode": entry.mode,
        "task_id": entry.task_id,
        "project_id": entry.project_id,
        "tokens_used": entry.tokens_used,
        "cost_usd": entry.cost_usd,
        "running": False,
        "model": entry.model,
        "started_at": entry.started_at,
        "pending_question": None,
        "branch": entry.branch,
        "advisory": entry.advisory,
        "role": entry.role,
        "last_activity": "",
    }


def create_router(session_manager: SessionManager, auth: Auth) -> APIRouter:
    router = APIRouter()

    @router.get("/api/agents")
    async def list_agents(project: str = Query("")):
        """Return all active sessions, optionally filtered by workspace."""
        sessions = session_manager.active
        if project:
            sessions = [s for s in sessions if s.project_id == project]
        return {"agents": [_agent_to_response(s) for s in sessions]}

    @router.get("/api/agents/pending-questions")
    async def list_pending_questions():
        """Return all sessions with an unanswered ask_user question.
        Polled by the notification bell so pending questions are visible
        from any view, not just the agent's thread."""
        items = []
        for s in session_manager.active:
            pq = s._pending_question
            if pq and pq.get("event") and not pq["event"].is_set():
                items.append({
                    "agent_id": s.id,
                    "task_id": s.task_id,
                    "question": pq.get("question", ""),
                    "options": pq.get("options"),
                })
        return {"questions": items}

    @router.get("/api/agent/{agent_id}/events")
    async def agent_events(agent_id: str, request: Request):
        """SSE endpoint for live agent events.

        Each connection gets its own subscriber queue (pre-seeded with
        recent history) via Session.subscribe(), so multiple simultaneous
        viewers of the same agent (e.g. two browser tabs, or a Dashboard
        card open alongside its Agent Thread) each see every event rather
        than racing for them on one shared queue.
        """
        session = session_manager.get(agent_id)
        sse_headers = {
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }

        if session is None:
            # Already stopped — replay its persisted wastebin history
            # once, then idle exactly like a live-but-quiet session
            # (keepalives, never actually closing the response) instead
            # of ending the stream. EventSource auto-reconnects on a
            # closed or errored connection regardless of what data was
            # sent, so ending it here would just re-replay the same
            # history in a loop forever rather than settling.
            from agent_knots.config import wastebin_dir
            from agent_knots.wastebin import WastebinStore

            entry = WastebinStore(wastebin_dir()).get(agent_id)
            if entry is None:
                raise HTTPException(status_code=404, detail="Agent not found")

            history = entry.history
            if not history or history[-1].get("type") != "ended":
                history = [*history, {
                    "type": "ended", "session_id": agent_id, "timestamp": entry.stopped_at,
                    "message": "Session stopped.", "tool_call": None, "tool_result": None,
                    "error": "", "data": None,
                }]

            async def replay_generator():
                yield "event: connected\ndata: {}\n\n"
                for event in history:
                    yield f"data: {json.dumps(event)}\n\n"
                try:
                    while True:
                        if await request.is_disconnected():
                            break
                        await asyncio.sleep(15.0)
                        yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    pass

            from fastapi.responses import StreamingResponse

            return StreamingResponse(replay_generator(), media_type="text/event-stream", headers=sse_headers)

        q = session.subscribe()

        async def event_generator():
            # Send initial connection event.
            yield "event: connected\ndata: {}\n\n"

            try:
                while True:
                    # Check if client disconnected.
                    if await request.is_disconnected():
                        break

                    try:
                        event = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # Send keepalive.
                        yield ": keepalive\n\n"
                        continue

                    yield f"data: {json.dumps(serialize_event(event))}\n\n"

            except asyncio.CancelledError:
                pass
            finally:
                session.unsubscribe(q)

        from fastapi.responses import StreamingResponse

        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=sse_headers)

    @router.get("/api/agent/{agent_id}")
    async def get_agent(agent_id: str):
        """Return a single session's detail (Task Detail's session-info
        side block, Agent Thread's header).

        Falls back to the wastebin if the session already stopped —
        reopening a finished session to see what it did shouldn't 404
        just because it isn't live anymore.
        """
        session = session_manager.get(agent_id)
        if session is not None:
            return _agent_to_response(session)

        from agent_knots.config import wastebin_dir
        from agent_knots.wastebin import WastebinStore

        entry = WastebinStore(wastebin_dir()).get(agent_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _wastebin_entry_to_agent_response(entry)

    @router.get("/api/agent/{agent_id}/file")
    async def get_agent_file(agent_id: str, path: str = Query(...)):
        """Read a file's current content for the Files tab's preview.

        Confined to the session's own working directory via the same
        path-resolution helper the sandboxed editor tool uses, when there
        is one. A session with no workspace never had a sandbox applied
        to its shell/editor tools either (see SessionManager.start()) —
        they already read/write anywhere on disk unconfined in that case,
        so there's no extra risk in previewing wherever the agent
        actually touched; just resolve the path as given (relative to
        this server process's own cwd, same as the unsandboxed tools).
        """
        session = session_manager.get(agent_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if session.working_dir:
            from agent_knots.sandbox_tools import _resolve
            try:
                resolved = _resolve(session.working_dir, path)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        else:
            resolved = str(Path(path).expanduser().resolve())

        file_path = Path(resolved)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        max_bytes = 500_000
        raw = file_path.read_bytes()
        truncated = len(raw) > max_bytes
        raw = raw[:max_bytes]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=415, detail="Binary file — can't preview as text")

        return {"path": path, "content": content, "truncated": truncated}

    @router.websocket("/api/agent/{agent_id}/terminal")
    async def agent_terminal(websocket: WebSocket, agent_id: str):
        """Real interactive terminal for the Files rail's Terminal tab —
        a PTY-backed shell rooted in the session's working directory (or
        this server process's own cwd if the session has none), streamed
        over this websocket. Same trust boundary as everything else: the
        agent's own shell tool already runs unconfined commands in this
        same environment, so a human getting an equivalent real terminal
        behind the same auth token isn't a new capability, just a UI for
        one that already exists.

        Websocket connections don't go through auth_middleware (Starlette
        only applies "http"-scope middleware, not "websocket"-scope), so
        auth is checked here directly — cookie or ?token=, same
        constant-time verify_token() as everywhere else.
        """
        token = websocket.cookies.get(COOKIE_NAME) or websocket.query_params.get("token", "")
        if not verify_token(token, auth.token):
            await websocket.close(code=4401)
            return
        if not HAS_PTY:
            await websocket.close(code=4501, reason="Terminal isn't supported on this platform")
            return

        session = session_manager.get(agent_id)
        if session is None:
            await websocket.close(code=4404)
            return

        await websocket.accept()

        cwd = session.working_dir or os.getcwd()
        shell_cmd = os.environ.get("SHELL", "/bin/bash")

        pid, fd = pty.fork()
        if pid == 0:
            # Child: replace this process image with a shell rooted at cwd.
            try:
                os.chdir(cwd)
            except OSError:
                pass
            os.execvp(shell_cmd, [shell_cmd])
            os._exit(1)  # only reached if execvp itself failed

        loop = asyncio.get_event_loop()
        output_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _on_readable() -> None:
            try:
                data = os.read(fd, 4096)
            except OSError:
                data = b""
            output_queue.put_nowait(data or None)  # empty read == child exited

        loop.add_reader(fd, _on_readable)

        async def _pump_output() -> None:
            while True:
                chunk = await output_queue.get()
                if chunk is None:
                    break
                await websocket.send_json({"type": "output", "data": chunk.decode(errors="replace")})

        pump_task = asyncio.create_task(_pump_output())

        try:
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "input":
                    os.write(fd, str(msg.get("data", "")).encode())
                elif msg.get("type") == "resize":
                    cols, rows = int(msg.get("cols", 80)), int(msg.get("rows", 24))
                    winsize = struct.pack("HHHH", rows, cols, 0, 0)
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            loop.remove_reader(fd)
            pump_task.cancel()
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                os.close(fd)
            except OSError:
                pass

    @router.post("/api/agent/{agent_id}/assume")
    async def agent_assume(agent_id: str):
        """Assume control of an agent (switch to assistant mode)."""
        await session_manager.set_mode(agent_id, "assistant")
        return {"status": "ok"}

    @router.post("/api/agent/{agent_id}/relinquish")
    async def agent_relinquish(agent_id: str):
        """Relinquish control of an agent (switch to agent mode)."""
        await session_manager.set_mode(agent_id, "agent")
        return {"status": "ok"}

    @router.post("/api/agent/{agent_id}/autonomous")
    @raises_as(404)
    async def agent_set_autonomous(agent_id: str, body: AutonomousRequest):
        """Toggle a task-attached session between autonomous (self-
        directed from the task) and paused (interactive). See
        SessionManager.set_autonomous()."""
        await session_manager.set_autonomous(agent_id, body.on)
        return {"status": "ok"}

    @router.post("/api/agent/{agent_id}/checkpoint")
    @raises_as(404)
    async def agent_checkpoint(agent_id: str, body: CheckpointRequest):
        """Mark a checkpoint — broadcasts a marker event only, no real
        snapshot (see SessionManager.checkpoint()'s docstring)."""
        session_manager.checkpoint(agent_id, body.label)
        return {"status": "ok"}

    @router.post("/api/agent/{agent_id}/revert")
    @raises_as(404)
    async def agent_revert(agent_id: str, body: CheckpointRequest):
        """"Revert to" a checkpoint — logs the action only, doesn't
        actually roll back any state (see SessionManager.revert())."""
        session_manager.revert(agent_id, body.label)
        return {"status": "ok"}

    @router.post("/api/agent/{agent_id}/send")
    async def agent_send(agent_id: str, message: str = Form(...)):
        """Send a message to an agent."""
        await session_manager.send(agent_id, message)
        return {"status": "ok"}

    @router.post("/api/agent/{agent_id}/interrupt")
    @raises_as(404)
    async def agent_interrupt(agent_id: str):
        """Cancel the agent's current turn only — the session stays open
        so a follow-up message continues the same conversation (unlike
        DELETE, which tears the session down)."""
        await session_manager.interrupt(agent_id)
        return {"status": "ok"}

    @router.post("/api/agent/{agent_id}/answer")
    @raises_as(404)
    async def agent_answer(agent_id: str, answer: str = Form(...)):
        """Answer a pending ask_user question from the agent.

        Resolves the blocking tool call so the agent can continue its
        turn with the user's answer. A no-op if no question is pending.
        """
        session = session_manager.get(agent_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        pending = session._pending_question
        if pending is None:
            return {"status": "ok", "answered": False}
        pending["answer"] = answer
        pending["event"].set()
        return {"status": "ok", "answered": True}

    @router.delete("/api/agent/{agent_id}")
    async def agent_delete(agent_id: str):
        """Stop and remove a session."""
        await session_manager.stop(agent_id)
        return {"status": "ok"}

    @router.post("/api/sessions")
    async def create_session(body: CreateSessionRequest):
        """Start a new agent session in the background.

        Deliberately doesn't pass model/api_key/base_url through from
        settings.load() here — that would always outrank env vars in
        resolve_provider()'s precedence (any explicitly-passed value
        there is treated as the highest-priority "CLI flag" tier), which
        silently broke env-var-only configuration for actual session
        starts even though the "configured" pre-flight check above
        already resolves the full precedence correctly. Leaving these
        unset lets SessionManager.start()'s own resolve_provider() call
        apply the real env > file precedence.
        """
        if not provider_module.resolve_provider().is_configured:
            raise HTTPException(status_code=400, detail="Settings not configured. Run setup first.")

        if body.task_id:
            task_store = TaskStore(tasks_dir())
            task = task_store.get(body.task_id)
            if task is not None:
                unmet = task_store.unmet_dependencies(task)
                if unmet:
                    blockers = ", ".join(f"{t.id} ({t.title})" for t in unmet)
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot start — task is blocked by unfinished dependencies: {blockers}",
                    )

            # Every session started through this route is a writer (the
            # only advisory sessions in the app come from role triggers,
            # see workflows/models.py) — refuse a second one on a task
            # that already has one active, rather than two agents
            # silently fighting over the same working tree/branch.
            existing = next(
                (s for s in session_manager.active if s.task_id == body.task_id and not s.advisory),
                None,
            )
            if existing is not None:
                raise HTTPException(
                    status_code=400,
                    detail=f"An agent ({existing.id}) is already working on this task.",
                )

        spend_cap = PolicyStore(policies_file()).get("spend_cap")
        if spend_cap is not None and spend_cap.enabled:
            try:
                cap = float(spend_cap.value)
            except (TypeError, ValueError):
                cap = 0.0
            if cap > 0:
                spent_today = usage_module.cost_since(usage_file(), usage_module.today_start())
                if spent_today >= cap:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Daily spend cap of ${cap:.2f} reached (${spent_today:.2f} spent today).",
                    )

        try:
            session = await session_manager.start(
                mode=body.mode,
                task_id=body.task_id,
                project_id=body.project_id,
                task_description=body.prompt,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except ValueError as e:
            # SessionManager.start() auto-transitions an 'open' task to
            # 'in_progress', which now goes through the same dependency
            # gate as everything else — the check above catches the
            # common case ahead of time, this is the fallback for it.
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "id": session.id,
            "mode": session.mode,
            "running": session.running,
        }

    return router
