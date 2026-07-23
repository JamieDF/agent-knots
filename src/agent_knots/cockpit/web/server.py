"""FastAPI web cockpit server.

Serves:
  - Static SPA assets (Vite build output, or inline HTML in dev mode)
  - REST API for session management
  - SSE endpoint for live event streaming
  - Token-based authentication
"""

import asyncio
import functools
import json
import os
import re
import secrets
import signal
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    import pty
    import fcntl
    import struct
    import termios
    HAS_PTY = True
except ImportError:  # Windows has no pty module
    HAS_PTY = False

from agent_knots.cockpit.web.auth import Auth, COOKIE_NAME, verify_token
from agent_knots.config import (
    cockpit_token_file, tasks_dir, stages_file, roles_file,
    vault_dir, usage_file, policies_file, mcp_servers_file,
)
from agent_knots.events import serialize_event
from agent_knots.session.manager import SessionManager
from agent_knots import provider as provider_module
from agent_knots import settings
from agent_knots import usage as usage_module
from agent_knots.task.store import TaskStore
from agent_knots.task.models import Task, TaskStatus, Priority, ReviewGate, Step, new_task_id
from agent_knots.tools.registry import ToolRegistry, CustomTool
from agent_knots.project.store import ProjectStore
from agent_knots.project.models import Project
from agent_knots.config import projects_dir as _projects_dir
from agent_knots.workflows.models import Trigger, stage_for_status
from agent_knots.workflows.store import RolesStore, StagesStore
from agent_knots.policies.store import PolicyStore
from agent_knots.mcp_servers import McpServer, McpServerStore
from agent_knots.vault.store import Credential, VaultStore


# ── request models (module-level so FastAPI can resolve them) ────────────────


class SaveSettingsRequest(BaseModel):
    default_model: str = "openai/gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    default_mode: str = ""
    runtime: str = ""


class CreateSessionRequest(BaseModel):
    prompt: str = ""
    mode: str = "agent"
    task_id: Optional[str] = None
    project_id: Optional[str] = None


class CheckpointRequest(BaseModel):
    label: str = "checkpoint"


class AutonomousRequest(BaseModel):
    on: bool


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    status: str = "draft"
    project: str = ""
    tags: list = []
    acceptance_criteria: list = []
    review_gate: str = "manual"
    dependencies: list = []


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assign: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list] = None
    acceptance_criteria: Optional[list] = None
    steps: Optional[list] = None  # list of step title strings
    review_gate: Optional[str] = None
    dependencies: Optional[list] = None


class ToggleCriterionRequest(BaseModel):
    criterion: str
    met: bool


class DraftTaskRequest(BaseModel):
    title: str


class ToggleRequest(BaseModel):
    enabled: bool


class UpdateRoleRequest(BaseModel):
    model: Optional[str] = None
    trigger: Optional[str] = None
    prompt: Optional[str] = None
    enabled: Optional[bool] = None


class ReviewActionRequest(BaseModel):
    workspace: str
    file: Optional[str] = None  # omitted = every pending file in the workspace


class UnlockVaultRequest(BaseModel):
    passphrase: str


class AddCredentialRequest(BaseModel):
    id: str
    description: str = ""
    tags: list = []
    value: str


class AddProviderRequest(BaseModel):
    name: str
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class UpdatePolicyRequest(BaseModel):
    enabled: Optional[bool] = None
    value: Optional[str] = None


class AddMcpServerRequest(BaseModel):
    name: str
    url: str = ""


class SaveIntegrationsRequest(BaseModel):
    github_pr_on_review: Optional[bool] = None
    phone_push: Optional[bool] = None


class CreateToolRequest(BaseModel):
    name: str
    description: str = ""
    command: str
    parameters: list = []  # list of {name, type, description}


class UpdateToolRequest(BaseModel):
    description: Optional[str] = None
    command: Optional[str] = None
    parameters: Optional[list] = None


def raises_as(status_code: int):
    """Route decorator: convert a ValueError raised inside the handler
    into an HTTPException with the given status code, so routes don't
    each hand-roll the same `try: ... except ValueError as e: raise
    HTTPException(status_code=N, detail=str(e))` (~17 near-identical
    copies of it before this existed — found in the code review).

    Stack directly under the FastAPI route decorator:

        @app.patch("/api/things/{key}")
        @raises_as(404)
        async def update_thing(key: str, body: UpdateRequest):
            return store.update(key, ...)  # raises ValueError if missing

    functools.wraps sets __wrapped__, which inspect.signature() (what
    FastAPI actually uses to resolve path/query/body parameters) follows
    by default — so FastAPI still sees the original handler's real
    signature through the wrapper, not a bare (*args, **kwargs). Verified
    directly against a real FastAPI app before applying this broadly.
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ValueError as e:
                raise HTTPException(status_code=status_code, detail=str(e))
        return wrapper

    return decorator


# ── app factory ──────────────────────────────────────────────────────────────


def create_app(
    session_manager: SessionManager,
    static_dir: Optional[Path] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        session_manager: The session manager to query for agents.
        static_dir: Path to the Vite build output directory. If None,
                    inline HTML is served (dev mode).
    """
    app = FastAPI(title="agent-knots cockpit")

    auth = Auth(cockpit_token_file())

    # Instantiated once per app (not per-request, unlike ToolRegistry/
    # ProjectStore/TaskStore above) because VaultStore's unlock state
    # (the derived key) lives in memory on the instance itself — a
    # fresh instance per request would forget it was ever unlocked.
    vault = VaultStore(vault_dir())

    # ── auth middleware ──────────────────────────────────────────────────

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """Authenticate all requests except /login, /api/health, and static files.

        Checks (in order): ?token= query param, the session cookie, then an
        Authorization: Bearer header (for programmatic/API clients). All
        three compare against the token with verify_token()'s constant-time
        comparison rather than a plain == — timing attacks on a token
        compare are a real (if narrow) risk worth not reintroducing.
        """
        path = request.url.path
        # Allow login, health, and static assets without auth.
        if path in ("/login", "/api/health") or path.startswith("/assets/"):
            return await call_next(request)
        token_qs = request.query_params.get("token", "")
        if verify_token(token_qs, auth.token):
            if path.startswith("/api/"):
                # SSE (EventSource can't set headers) and other API calls —
                # let the request straight through, no redirect.
                return await call_next(request)
            # Any other path — the SPA shell or a deep link (e.g. the
            # printed "one-click" cockpit URL, `/?token=...`). Previously
            # this branch only fired for /api/* paths, so opening that URL
            # in a browser fell through to the login page instead of
            # actually logging in. Set the cookie and redirect to the same
            # URL with the token stripped, so it doesn't linger in the
            # address bar/history any longer than it takes to log in.
            remaining = [(k, v) for k, v in request.query_params.multi_items() if k != "token"]
            clean_url = path + ("?" + urlencode(remaining) if remaining else "")
            return auth.set_cookie_redirect(clean_url)
        # Cookie.
        if verify_token(request.cookies.get(COOKIE_NAME, ""), auth.token):
            return await call_next(request)
        # Authorization: Bearer header, for non-browser clients.
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and verify_token(auth_header[7:], auth.token):
            return await call_next(request)
        # HTMX requests get 401, browser gets redirect to login.
        if request.headers.get("HX-Request"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse(url="/login?return=" + request.url.path, status_code=303)

    # ── login ────────────────────────────────────────────────────────────

    @app.get("/login")
    async def login_page(request: Request, return_url: str = Query("/", alias="return")):
        return HTMLResponse(LOGIN_HTML.format(
            return_url=return_url or "/",
            error="",
        ))

    @app.post("/login")
    async def login_post(token: str = Form(...), return_url: str = Form("/")):
        if not verify_token(token, auth.token):
            return HTMLResponse(LOGIN_HTML.format(
                return_url=return_url,
                error="Invalid token.",
            ))
        return auth.set_cookie_redirect(return_url or "/")

    # ── SPA shell ────────────────────────────────────────────────────────

    def _spa_html() -> str:
        """The SPA shell HTML. In prod mode, this is the Vite-built index.html."""
        if static_dir and (static_dir / "index.html").exists():
            return (static_dir / "index.html").read_text()
        return SPA_SHELL_HTML

    @app.get("/")
    async def index():
        """Serve the SPA shell. In prod mode, this is the Vite-built index.html."""
        return HTMLResponse(_spa_html())

    # ── REST API ─────────────────────────────────────────────────────────

    @app.get("/api/agents")
    async def list_agents(project: str = Query("")):
        """Return all active sessions, optionally filtered by workspace."""
        sessions = session_manager.active
        if project:
            sessions = [s for s in sessions if s.project_id == project]
        return {"agents": [_agent_to_response(s) for s in sessions]}

    @app.get("/api/agent/{agent_id}/events")
    async def agent_events(agent_id: str, request: Request):
        """SSE endpoint for live agent events.

        Each connection gets its own subscriber queue (pre-seeded with
        recent history) via Session.subscribe(), so multiple simultaneous
        viewers of the same agent (e.g. two browser tabs, or a Dashboard
        card open alongside its Agent Thread) each see every event rather
        than racing for them on one shared queue.
        """
        session = session_manager.get(agent_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Agent not found")

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

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/agent/{agent_id}")
    async def get_agent(agent_id: str):
        """Return a single session's detail (Task Detail's session-info
        side block, Agent Thread's header)."""
        session = session_manager.get(agent_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _agent_to_response(session)

    @app.get("/api/agent/{agent_id}/file")
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

    @app.websocket("/api/agent/{agent_id}/terminal")
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

    @app.post("/api/agent/{agent_id}/assume")
    async def agent_assume(agent_id: str):
        """Assume control of an agent (switch to assistant mode)."""
        await session_manager.set_mode(agent_id, "assistant")
        return {"status": "ok"}

    @app.post("/api/agent/{agent_id}/relinquish")
    async def agent_relinquish(agent_id: str):
        """Relinquish control of an agent (switch to agent mode)."""
        await session_manager.set_mode(agent_id, "agent")
        return {"status": "ok"}

    @app.post("/api/agent/{agent_id}/autonomous")
    @raises_as(404)
    async def agent_set_autonomous(agent_id: str, body: AutonomousRequest):
        """Toggle a task-attached session between autonomous (self-
        directed from the task) and paused (interactive). See
        SessionManager.set_autonomous()."""
        await session_manager.set_autonomous(agent_id, body.on)
        return {"status": "ok"}

    @app.post("/api/agent/{agent_id}/checkpoint")
    @raises_as(404)
    async def agent_checkpoint(agent_id: str, body: CheckpointRequest):
        """Mark a checkpoint — broadcasts a marker event only, no real
        snapshot (see SessionManager.checkpoint()'s docstring)."""
        session_manager.checkpoint(agent_id, body.label)
        return {"status": "ok"}

    @app.post("/api/agent/{agent_id}/revert")
    @raises_as(404)
    async def agent_revert(agent_id: str, body: CheckpointRequest):
        """"Revert to" a checkpoint — logs the action only, doesn't
        actually roll back any state (see SessionManager.revert())."""
        session_manager.revert(agent_id, body.label)
        return {"status": "ok"}

    @app.post("/api/agent/{agent_id}/send")
    async def agent_send(agent_id: str, message: str = Form(...)):
        """Send a message to an agent."""
        await session_manager.send(agent_id, message)
        return {"status": "ok"}

    @app.post("/api/agent/{agent_id}/interrupt")
    @raises_as(404)
    async def agent_interrupt(agent_id: str):
        """Cancel the agent's current turn only — the session stays open
        so a follow-up message continues the same conversation (unlike
        DELETE, which tears the session down)."""
        await session_manager.interrupt(agent_id)
        return {"status": "ok"}

    @app.delete("/api/agent/{agent_id}")
    async def agent_delete(agent_id: str):
        """Stop and remove a session."""
        await session_manager.stop(agent_id)
        return {"status": "ok"}

    # ── settings API ─────────────────────────────────────────────────────

    @app.get("/api/settings")
    async def get_settings():
        """Return current settings (API key masked).

        "configured" reflects whether a session could actually be started
        right now — CLI flags aren't relevant here, but env vars are, so
        this checks the same resolve_provider() precedence SessionManager
        uses rather than only the settings file. Otherwise a GUI user who
        configured via AGENT_KNOTS_API_KEY would get stuck behind the
        setup wizard even though sessions would actually work.
        """
        s = settings.load()
        return {
            "configured": provider_module.resolve_provider().is_configured,
            "agent": {
                "default_model": s.agent.default_model,
                "api_key": settings.mask_key(s.agent.api_key),
                "base_url": s.agent.base_url,
                "default_mode": s.agent.default_mode,
                "runtime": s.agent.runtime,
            },
            "providers": _providers_to_response(s),
            "default_provider": s.default_provider,
            "integrations": {
                "github_pr_on_review": s.integrations.github_pr_on_review,
                "phone_push": s.integrations.phone_push,
            },
        }

    @app.put("/api/settings")
    async def save_settings(body: SaveSettingsRequest):
        """Save settings. Empty fields preserve existing values."""
        s = settings.load()

        if body.default_model:
            s.agent.default_model = body.default_model
        if body.base_url:
            s.agent.base_url = body.base_url
        if body.default_mode:
            s.agent.default_mode = body.default_mode
        if body.runtime:
            s.agent.runtime = body.runtime

        # Only update API key if a real value was provided (not masked).
        if body.api_key and "..." not in body.api_key and not body.api_key.startswith("****"):
            s.agent.api_key = body.api_key

        settings.save(s)
        return {"status": "ok", "configured": provider_module.resolve_provider().is_configured}

    @app.post("/api/settings/providers")
    async def add_provider(body: AddProviderRequest):
        """Save a named provider profile. Doesn't touch resolve_provider()'s
        active config — only 'Set default' below does that."""
        s = settings.load()
        if any(p.name == body.name for p in s.providers):
            raise HTTPException(status_code=409, detail=f"Provider {body.name!r} already exists")
        s.providers.append(settings.ProviderProfile(
            name=body.name, model=body.model, api_key=body.api_key, base_url=body.base_url,
        ))
        settings.save(s)
        return {"providers": _providers_to_response(s)}

    @app.delete("/api/settings/providers/{name}")
    async def delete_provider(name: str):
        s = settings.load()
        remaining = [p for p in s.providers if p.name != name]
        if len(remaining) == len(s.providers):
            raise HTTPException(status_code=404, detail="Provider not found")
        s.providers = remaining
        if s.default_provider == name:
            s.default_provider = ""
        settings.save(s)
        return {"providers": _providers_to_response(s)}

    @app.post("/api/settings/providers/{name}/default")
    async def set_default_provider(name: str):
        """Make a saved provider profile the active one — copies its
        model/key/url into `agent`, which is what resolve_provider()
        actually reads. Never touches env-var precedence."""
        s = settings.load()
        profile = next((p for p in s.providers if p.name == name), None)
        if profile is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        s.agent.default_model = profile.model
        s.agent.api_key = profile.api_key
        s.agent.base_url = profile.base_url
        s.default_provider = name
        settings.save(s)
        return {"status": "ok", "default_provider": name}

    @app.put("/api/integrations")
    async def save_integrations(body: SaveIntegrationsRequest):
        s = settings.load()
        if body.github_pr_on_review is not None:
            s.integrations.github_pr_on_review = body.github_pr_on_review
        if body.phone_push is not None:
            s.integrations.phone_push = body.phone_push
        settings.save(s)
        return {"status": "ok"}

    # ── usage API ─────────────────────────────────────────────────────────

    @app.get("/api/usage")
    async def get_usage():
        return usage_module.summary(usage_file())

    # ── policies API ──────────────────────────────────────────────────────

    @app.get("/api/policies")
    async def list_policies():
        return {"policies": [_policy_to_response(p) for p in PolicyStore(policies_file()).list()]}

    @app.patch("/api/policies/{key}")
    @raises_as(404)
    async def update_policy(key: str, body: UpdatePolicyRequest):
        policy = PolicyStore(policies_file()).update(key, **body.model_dump(exclude_unset=True))
        return _policy_to_response(policy)

    # ── MCP server registry API (config-only — no real client wiring) ────

    @app.get("/api/mcp")
    async def list_mcp_servers():
        return {"servers": [_mcp_to_response(s) for s in McpServerStore(mcp_servers_file()).list()]}

    @app.post("/api/mcp")
    @raises_as(409)
    async def add_mcp_server(body: AddMcpServerRequest):
        store = McpServerStore(mcp_servers_file())
        store.add(McpServer(name=body.name, url=body.url))
        return {"servers": [_mcp_to_response(s) for s in store.list()]}

    @app.post("/api/mcp/{name}/toggle")
    @raises_as(404)
    async def toggle_mcp_server(name: str, body: ToggleRequest):
        store = McpServerStore(mcp_servers_file())
        server = store.toggle(name, body.enabled)
        return _mcp_to_response(server)

    @app.delete("/api/mcp/{name}")
    @raises_as(404)
    async def delete_mcp_server(name: str):
        store = McpServerStore(mcp_servers_file())
        store.remove(name)
        return {"status": "ok"}

    # ── vault API — metadata only, values never leave the store ─────────

    @app.get("/api/vault/status")
    async def vault_status():
        return {"lock_state": vault.lock_state.value}

    @app.post("/api/vault/unlock")
    @raises_as(400)
    async def vault_unlock(body: UnlockVaultRequest):
        vault.unlock(body.passphrase)
        return {"lock_state": vault.lock_state.value}

    @app.post("/api/vault/lock")
    async def vault_lock():
        vault.lock()
        return {"lock_state": vault.lock_state.value}

    @app.get("/api/vault/credentials")
    async def list_credentials():
        if not vault.unlocked:
            raise HTTPException(status_code=403, detail="Vault is locked")
        return {"credentials": [_credential_to_response(c) for c in vault.list_credentials()]}

    @app.post("/api/vault/credentials")
    async def add_credential(body: AddCredentialRequest):
        cred = Credential(id=body.id, description=body.description, tags=body.tags, value=body.value)
        try:
            vault.add_credential(cred)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "ok", "id": cred.id}

    @app.delete("/api/vault/credentials/{cred_id}")
    async def delete_credential(cred_id: str):
        try:
            vault.remove_credential(cred_id)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "ok"}

    @app.get("/api/vault/audit")
    async def vault_audit(limit: int = Query(50)):
        from agent_knots.vault.store import AuditOptions
        entries = vault.audit_log(AuditOptions(limit=limit))
        return {"entries": [
            {
                "timestamp": e.timestamp, "credential": e.credential, "template": e.template,
                "command": e.command, "caller": e.caller, "success": e.success, "error": e.error,
            }
            for e in entries
        ]}

    # ── session management API ────────────────────────────────────────────

    @app.post("/api/sessions")
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

    # ── task API ─────────────────────────────────────────────────────────

    @app.get("/api/tasks")
    async def list_tasks(
        status: str = Query(""),
        project: str = Query(""),
        limit: int = Query(0),
    ):
        """List tasks with optional filters."""
        store = TaskStore(tasks_dir())
        tasks = store.list(status=status, project=project, limit=limit)
        return {
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "priority": t.priority.value,
                    "tags": t.tags,
                    "project": t.project,
                    "assigned_to": t.assigned_to,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                    "progress_count": len(t.progress),
                    "steps_count": len(t.steps),
                    "criteria_count": len(t.acceptance_criteria),
                    "blocked_by_deps": len(store.unmet_dependencies(t)) > 0,
                }
                for t in tasks
            ]
        }

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        """Get full task details."""
        store = TaskStore(tasks_dir())
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return _task_to_response(task, store)

    @app.post("/api/tasks")
    async def create_task(body: CreateTaskRequest):
        """Create a new task."""
        store = TaskStore(tasks_dir())
        task = Task(
            id=new_task_id(body.project),
            title=body.title,
            description=body.description,
            priority=Priority(body.priority),
            status=TaskStatus(body.status) if body.status else TaskStatus.DRAFT,
            project=body.project,
            tags=body.tags,
            acceptance_criteria=body.acceptance_criteria,
            review_gate=ReviewGate(body.review_gate),
            dependencies=body.dependencies,
        )
        store.create(task)
        return _task_to_response(task, store)

    def _maybe_fire_role_triggers(old_status: str, new_status: str, task: Task) -> None:
        """Auto-start a session for any enabled default-agent role whose
        trigger matches this status transition (Workflows screen).

        Only wired at this API layer — a status change driven by an
        agent tool (task/tools.py's update_task_status/log_progress)
        does not fire triggers yet. Disclosed limitation, not silently
        incomplete: covering the agent-tool path would need threading
        SessionManager into the task-tools module, a bigger change
        deferred past this phase.
        """
        stages = StagesStore(stages_file()).list()
        old_stage = stage_for_status(stages, old_status)
        new_stage = stage_for_status(stages, new_status)
        if old_stage is None or new_stage is None or old_stage.key == new_stage.key:
            return

        # Independent checks, not if/elif — tasks now start in Draft by
        # default, so a single PATCH can jump straight from draft to
        # in_progress (skipping Open entirely) and should fire *both*
        # the leaves-draft and is-started triggers, not just one.
        triggers: list[Trigger] = []
        if old_stage.key == "draft" and new_stage.key != "draft":
            triggers.append(Trigger.LEAVES_DRAFT)
        if new_stage.key == "in_progress":
            triggers.append(Trigger.IS_STARTED)
        if new_stage.key == "review":
            triggers.append(Trigger.ENTERS_REVIEW)

        for trigger in triggers:
            for role in RolesStore(roles_file()).enabled_for_trigger(trigger):
                asyncio.create_task(session_manager.start(
                    mode="agent",
                    model=role.model,
                    system_prompt=role.prompt,
                    task_id=task.id,
                    task_description=f"({role.name}) {task.title}",
                ))

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, body: UpdateTaskRequest):
        """Update a task's status, priority, assignment, or content fields.

        Criteria/steps are matched against existing entries by text so
        criteria_met / step status survive an edit that doesn't touch
        them — a blind overwrite would silently reset that state.

        Mutates the in-memory task across all the content-field checks
        below and writes once at the end, rather than a separate
        store.update() per field (a PATCH touching several fields used
        to do several redundant full-file disk writes and bump
        updated_at repeatedly instead of once). status and assign are
        each still their own store call — both TaskStore.set_status()
        and .assign() re-fetch the task from disk themselves, so unlike
        the plain content fields they can't just be batched into the
        in-memory object. status runs first and assign runs last so
        each sees whatever the other steps have already persisted.
        """
        store = TaskStore(tasks_dir())
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        old_status = task.status.value
        if body.status:
            try:
                task = store.set_status(task_id, TaskStatus(body.status), actor="human")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            _maybe_fire_role_triggers(old_status, task.status.value, task)

        dirty = False
        if body.priority:
            task.priority = Priority(body.priority)
            dirty = True
        if body.title:
            task.title = body.title
            dirty = True
        if body.description is not None:
            task.description = body.description
            dirty = True
        if body.tags is not None:
            task.tags = body.tags
            dirty = True
        if body.review_gate is not None:
            task.review_gate = ReviewGate(body.review_gate)
            dirty = True
        if body.dependencies is not None:
            task.dependencies = [d for d in body.dependencies if d != task_id]
            dirty = True
        if body.acceptance_criteria is not None:
            # criteria_met is keyed by criterion text, so preserving it
            # here is automatic — no matching needed, just don't touch it.
            task.acceptance_criteria = body.acceptance_criteria
            task.criteria_met = [c for c in task.criteria_met if c in body.acceptance_criteria]
            dirty = True
        if body.steps is not None:
            existing_by_title = {s.title: s for s in task.steps}
            new_steps = []
            for title in body.steps:
                existing = existing_by_title.get(title)
                if existing is not None:
                    new_steps.append(existing)
                else:
                    new_steps.append(Step(id=f"s-{secrets.token_hex(3)}", title=title))
            task.steps = new_steps
            dirty = True
        if dirty:
            task = store.update(task)

        if body.assign is not None:
            task = store.assign(task_id, body.assign)

        return _task_to_response(task, store)

    @app.post("/api/tasks/{task_id}/criteria/toggle")
    @raises_as(404)
    async def toggle_criterion(task_id: str, body: ToggleCriterionRequest):
        """Mark/unmark a single acceptance criterion as met."""
        store = TaskStore(tasks_dir())
        if body.met:
            task = store.mark_criterion_met(task_id, body.criterion)
        else:
            task = store.unmark_criterion_met(task_id, body.criterion)
        return _task_to_response(task, store)

    @app.post("/api/tasks/draft")
    async def draft_task(body: DraftTaskRequest):
        """Draft a task's description/criteria/tags/steps from a title
        via a single non-tool-calling completion. Used by the "✨ Draft
        with agent" button in the create/edit dialog — no Strands Agent
        or session lifecycle involved, just one structured completion."""
        provider = provider_module.resolve_provider()
        if not provider.is_configured:
            raise HTTPException(status_code=400, detail="Settings not configured. Run setup first.")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url or None)
        prompt = (
            "Given a task title, draft a JSON object with fields: "
            "description (string), acceptance_criteria (list of strings), "
            "tags (list of strings), steps (list of strings). "
            "Respond with ONLY the raw JSON object — no markdown code fences, "
            "no commentary before or after it, no <think> reasoning block, "
            "no explanation of your reasoning at all — the very first "
            "character of your response must be '{'.\n\n"
            f"Title: {body.title}"
        )
        try:
            # No response_format — it's an OpenAI-specific strict-JSON-mode
            # parameter that not every OpenAI-*compatible* provider (e.g.
            # MiniMax) actually implements, and this app always goes
            # through OpenAIModel/AsyncOpenAI regardless of provider (see
            # provider.py). Passing an unsupported param 400s the whole
            # request instead of just getting a slightly less strict
            # completion, so ask for raw JSON in the prompt instead and
            # parse leniently below.
            resp = await client.chat.completions.create(
                model=provider.model,
                messages=[{"role": "user", "content": prompt}],
            )
            draft = _extract_json_object(resp.choices[0].message.content or "")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Draft generation failed: {e}")

        return {
            "description": draft.get("description", ""),
            "acceptance_criteria": draft.get("acceptance_criteria", []),
            "tags": draft.get("tags", []),
            "steps": draft.get("steps", []),
        }

    @app.delete("/api/tasks/{task_id}")
    @raises_as(404)
    async def delete_task(task_id: str):
        """Delete a task."""
        store = TaskStore(tasks_dir())
        store.delete(task_id)
        return {"status": "ok"}

    # ── tool API ─────────────────────────────────────────────────────────

    @app.get("/api/tools")
    async def list_tools():
        """List all tools (built-in + custom)."""
        registry = ToolRegistry()
        tools = registry.list_all()
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "builtin": t.builtin,
                    "enabled": t.enabled,
                    "created_at": t.created_at,
                }
                for t in tools
            ]
        }

    @app.get("/api/tools/{name}")
    async def get_tool(name: str):
        """Get a custom tool's full definition."""
        registry = ToolRegistry()
        ct = registry.get_custom(name)
        if ct is None:
            raise HTTPException(status_code=404, detail="Custom tool not found")
        return {
            "name": ct.name,
            "description": ct.description,
            "command": ct.command,
            "parameters": ct.parameters,
            "enabled": ct.enabled,
            "created_at": ct.created_at,
        }

    @app.post("/api/tools")
    @raises_as(409)
    async def create_tool(body: CreateToolRequest):
        """Create a new custom tool."""
        registry = ToolRegistry()
        ct = CustomTool(
            name=body.name,
            description=body.description,
            command=body.command,
            parameters=body.parameters,
        )
        registry.add_custom(ct)
        return {"status": "ok", "name": ct.name}

    @app.patch("/api/tools/{name}")
    async def update_tool(name: str, body: UpdateToolRequest):
        """Update a custom tool."""
        registry = ToolRegistry()
        ct = registry.get_custom(name)
        if ct is None:
            raise HTTPException(status_code=404, detail="Custom tool not found")
        if body.description is not None:
            ct.description = body.description
        if body.command is not None:
            ct.command = body.command
        if body.parameters is not None:
            ct.parameters = body.parameters
        registry.update_custom(ct)
        return {"status": "ok"}

    @app.delete("/api/tools/{name}")
    @raises_as(404)
    async def delete_tool(name: str):
        """Delete a custom tool."""
        registry = ToolRegistry()
        registry.delete_custom(name)
        return {"status": "ok"}

    @app.post("/api/tools/{name}/toggle")
    @raises_as(404)
    async def toggle_tool(name: str):
        """Toggle a tool's enabled state (built-in or custom)."""
        tool = ToolRegistry().toggle(name)
        return {"enabled": tool.enabled}

    # ── workspace API ────────────────────────────────────────────────────

    @app.get("/api/workspaces")
    async def list_workspaces(include_archived: bool = Query(False)):
        """List workspaces (projects). Archived workspaces are hidden by
        default — pass include_archived=true (Settings' management view) to
        see them too."""
        store = ProjectStore(_projects_dir())
        workspaces = store.list()
        if not include_archived:
            workspaces = [w for w in workspaces if not w.archived]
        return {
            "workspaces": [
                {
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "repository": w.repository,
                    "runtime": w.runtime,
                    "tags": w.tags,
                    "auto_assign": w.auto_assign,
                    "max_concurrent": w.max_concurrent,
                    "archived": w.archived,
                    "created_at": w.created_at,
                }
                for w in workspaces
            ]
        }

    class CreateWorkspaceRequest(BaseModel):
        id: Optional[str] = None  # omitted = slugify from name, deduped
        name: str
        description: str = ""
        repository: str = ""
        runtime: str = ""
        tags: list = []
        auto_assign: bool = False
        max_concurrent: int = 2

    @app.post("/api/workspaces")
    @raises_as(409)
    async def create_workspace(body: CreateWorkspaceRequest):
        """Create a new workspace."""
        store = ProjectStore(_projects_dir())
        ws = Project(
            id=body.id or _unique_project_id(store, body.name),
            name=body.name,
            description=body.description,
            repository=body.repository,
            runtime=body.runtime,
            tags=body.tags,
            auto_assign=body.auto_assign,
            max_concurrent=body.max_concurrent,
        )
        store.create(ws)
        return {"status": "ok", "id": ws.id}

    class UpdateWorkspaceRequest(BaseModel):
        name: Optional[str] = None
        description: Optional[str] = None
        repository: Optional[str] = None
        runtime: Optional[str] = None
        tags: Optional[list] = None
        auto_assign: Optional[bool] = None
        max_concurrent: Optional[int] = None
        archived: Optional[bool] = None

    @app.patch("/api/workspaces/{workspace_id}")
    async def update_workspace(workspace_id: str, body: UpdateWorkspaceRequest):
        """Update a workspace."""
        store = ProjectStore(_projects_dir())
        ws = store.get(workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if body.name is not None:
            ws.name = body.name
        if body.description is not None:
            ws.description = body.description
        if body.repository is not None:
            ws.repository = body.repository
        if body.runtime is not None:
            ws.runtime = body.runtime
        if body.tags is not None:
            ws.tags = body.tags
        if body.auto_assign is not None:
            ws.auto_assign = body.auto_assign
        if body.max_concurrent is not None:
            ws.max_concurrent = body.max_concurrent
        if body.archived is not None:
            ws.archived = body.archived
        store.update(ws)
        return {"status": "ok"}

    @app.delete("/api/workspaces/{workspace_id}")
    @raises_as(404)
    async def delete_workspace(workspace_id: str):
        """Delete a workspace."""
        store = ProjectStore(_projects_dir())
        store.delete(workspace_id)
        return {"status": "ok"}

    # ── workflows API (stages + default agent roles) ────────────────────

    @app.get("/api/stages")
    async def list_stages():
        return {"stages": [
            {"key": s.key, "label": s.label, "statuses": s.statuses, "enabled": s.enabled, "required": s.required}
            for s in StagesStore(stages_file()).list()
        ]}

    @app.post("/api/stages/{key}/toggle")
    @raises_as(400)
    async def toggle_stage(key: str, body: ToggleRequest):
        stages = StagesStore(stages_file()).toggle(key, body.enabled)
        return {"stages": [
            {"key": s.key, "label": s.label, "statuses": s.statuses, "enabled": s.enabled, "required": s.required}
            for s in stages
        ]}

    @app.get("/api/roles")
    async def list_roles():
        return {"roles": [_role_to_response(r) for r in RolesStore(roles_file()).list()]}

    @app.patch("/api/roles/{key}")
    @raises_as(404)
    async def update_role(key: str, body: UpdateRoleRequest):
        role = RolesStore(roles_file()).update(key, **body.model_dump(exclude_unset=True))
        return _role_to_response(role)

    # ── review API (post-hoc diffs derived live from git) ────────────────
    #
    # No separate diff-capture/staging layer — pending diffs are just
    # each configured workspace's current uncommitted git changes,
    # per WORKPLAN.md's Phase 4 decoupling note. Approve stages+commits
    # a specific file (or everything pending, for approve-all). Reject
    # deliberately does NOT discard the changes — git checkout/reset/
    # clean against a real repo is a destructive action this won't
    # automate; it only acknowledges, matching the design's own
    # "Rejected — agent notified" copy (notifies, doesn't destroy).

    @app.get("/api/review/diffs")
    async def list_review_diffs():
        items = []
        for p in ProjectStore(_projects_dir()).list():
            if not p.repository:
                continue
            repo = Path(p.repository)
            if not (repo / ".git").is_dir():
                continue
            for f in _git_diff_stat(repo):
                items.append({
                    "workspace": p.id, "workspace_name": p.name,
                    "file": f["path"], "added": f["added"], "deleted": f["deleted"],
                })
        return {"diffs": items}

    @app.get("/api/review/diff")
    async def get_review_diff(workspace: str = Query(...), file: str = Query(...)):
        proj = ProjectStore(_projects_dir()).get(workspace)
        if proj is None or not proj.repository:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return {"diff": _git_diff_for_file(Path(proj.repository), file)}

    @app.post("/api/review/approve")
    async def approve_review(body: ReviewActionRequest):
        repo = _review_repo_or_404(body.workspace)
        add_result = _run_git(repo, ["add", "--", body.file] if body.file else ["add", "-A"])
        if add_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git add failed: {add_result.stderr.strip()}")
        commit_result = _run_git(repo, ["commit", "-m", "Approved via cockpit Review queue"])
        if commit_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git commit failed: {commit_result.stderr.strip()}")
        return {"status": "committed"}

    @app.post("/api/review/reject")
    async def reject_review(body: ReviewActionRequest):
        _review_repo_or_404(body.workspace)  # validates the workspace exists
        return {"status": "rejected", "note": "Not discarded — reject only acknowledges."}

    def _review_repo_or_404(workspace_id: str) -> Path:
        proj = ProjectStore(_projects_dir()).get(workspace_id)
        if proj is None or not proj.repository:
            raise HTTPException(status_code=404, detail="Workspace not found")
        repo = Path(proj.repository)
        if not (repo / ".git").is_dir():
            raise HTTPException(status_code=400, detail="Not a git repository")
        return repo

    # ── filesystem browse API (workspace folder picker) ──────────────────
    #
    # This is a local-first, single-user app that already lets you point a
    # workspace at any local path and run shell commands in it — browsing
    # directory names isn't a new trust boundary on top of that, but it's
    # still directories-only (no file contents) and confined to what the
    # local user running the server can already see.

    @app.get("/api/fs/browse")
    async def browse_fs(path: str = Query("")):
        base = Path(path).expanduser() if path else Path.home()
        try:
            base = base.resolve()
        except OSError:
            raise HTTPException(status_code=400, detail="Invalid path")
        if not base.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        try:
            children = sorted(
                (c for c in base.iterdir() if c.is_dir() and not c.name.startswith(".")),
                key=lambda c: c.name.lower(),
            )
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        entries = [
            {"name": c.name, "path": str(c), "is_git": (c / ".git").exists()}
            for c in children
        ]
        parent = str(base.parent) if base.parent != base else None
        return {"path": str(base), "parent": parent, "entries": entries}

    @app.get("/api/fs/git-info")
    async def fs_git_info(path: str = Query(...)):
        repo = Path(path).expanduser()
        if not (repo / ".git").exists():
            return {"is_git": False, "github_url": None}
        result = _run_git(repo, ["remote", "get-url", "origin"])
        if result.returncode != 0:
            return {"is_git": True, "github_url": None}
        return {"is_git": True, "github_url": _github_url_from_remote(result.stdout.strip())}

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "agents": len(session_manager.active)}

    # ── static files (prod mode) ─────────────────────────────────────────

    if static_dir and static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # ── SPA fallback (BrowserRouter support) ─────────────────────────────
    # Registered last so it never shadows /api/* or /assets/* routes —
    # Starlette matches routes in registration order, and a `path:`
    # converter registered earlier would swallow everything below it.
    # Needed because the frontend now uses real paths (not hash routing),
    # so a hard refresh/bookmark on e.g. /tasks/T-123 hits this server
    # directly and must get the SPA shell, not a 404.
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("assets/"):
            raise HTTPException(status_code=404, detail="Not found")
        return HTMLResponse(_spa_html())

    return app


# ── serialization helpers ────────────────────────────────────────────────────


def _agent_to_response(session) -> dict:
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
    }


def _role_to_response(role) -> dict:
    return {
        "key": role.key, "name": role.name, "icon": role.icon, "description": role.description,
        "model": role.model, "trigger": role.trigger.value, "prompt": role.prompt,
        "tools": role.tools, "enabled": role.enabled,
    }


def _providers_to_response(s: "settings.Settings") -> list[dict]:
    """Saved provider profiles, plus (if none are saved yet but a legacy
    single-provider config already exists) a synthetic 'default' entry
    so existing installs don't see an empty list. Never returns a raw
    api_key — only whether one is set."""
    if s.providers:
        return [
            {
                "name": p.name, "model": p.model, "base_url": p.base_url,
                "key_set": bool(p.api_key), "is_default": p.name == s.default_provider,
            }
            for p in s.providers
        ]
    if s.agent.api_key:
        return [{
            "name": "default", "model": s.agent.default_model, "base_url": s.agent.base_url,
            "key_set": True, "is_default": True,
        }]
    return []


def _policy_to_response(p) -> dict:
    return {
        "key": p.key, "label": p.label, "description": p.description,
        "enabled": p.enabled, "value": p.value, "enforced": p.enforced,
    }


def _mcp_to_response(s) -> dict:
    return {
        "name": s.name, "url": s.url, "enabled": s.enabled,
        "tool_count": s.tool_count, "created_at": s.created_at,
    }


def _credential_to_response(c) -> dict:
    """Metadata only — deliberately does not reference c.value at all,
    even though the store never populates it from list_credentials()."""
    return {
        "id": c.id, "description": c.description, "tags": c.tags,
        "created_at": c.created_at, "last_used": c.last_used, "uses_total": c.uses_total,
        "templates": [
            {"name": t.name, "description": t.description, "env": t.env, "file_path": t.file_path,
             "stdin": t.stdin, "command_wrapper": t.command_wrapper}
            for t in c.templates
        ],
    }


def _run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Run a git command scoped to a workspace repo the user configured
    themselves (Project.repository) — never an arbitrary path, never
    shell=True (no injection risk from list-form subprocess args)."""
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=10,
    )


def _git_diff_stat(repo: Path) -> list[dict]:
    """Per-file added/deleted line counts for uncommitted changes."""
    result = _run_git(repo, ["diff", "--numstat"])
    items = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, deleted, path = parts
            items.append({
                "path": path,
                "added": int(added) if added.isdigit() else 0,
                "deleted": int(deleted) if deleted.isdigit() else 0,
            })
    return items


def _git_diff_for_file(repo: Path, path: str) -> str:
    return _run_git(repo, ["diff", "--", path]).stdout


def _extract_json_object(text: str) -> dict:
    """Parse a JSON object out of a completion's raw text, tolerating the
    markdown code fences, stray commentary, and <think>...</think>
    reasoning blocks models commonly add even when explicitly told not
    to (no response_format to enforce it — see draft_task()). MiniMax
    M2.7 in particular is a reasoning model that inlines its <think>
    block directly into `message.content` for a plain, non-streaming
    completion (there's no separate reasoning field to skip) — and
    since reasoning text about a coding task routinely contains its own
    literal '{'/'}' characters, a naive "first { to last }" scan can
    grab braces from *inside* the reasoning instead of the real JSON
    object, producing something that isn't valid JSON at all."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    snippet = text[:200] + ("…" if len(text) > 200 else "")
    raise ValueError(f"No valid JSON object found in completion: {snippet!r}")


def _unique_project_id(store: ProjectStore, name: str) -> str:
    """Slugify a workspace name into an id, deduping against existing
    workspaces — lets the create-workspace dialog drop the id field
    entirely and just ask for a name."""
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "workspace"
    candidate = base
    n = 2
    while store.get(candidate) is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _github_url_from_remote(remote_url: str) -> str | None:
    """Best-effort parse of a git remote URL into a browsable
    https://github.com/owner/repo link, covering the SSH, ssh://, and
    HTTPS forms `git remote get-url origin` can return."""
    url = remote_url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    for pattern in (r"^git@github\.com:(.+)$", r"^ssh://git@github\.com/(.+)$", r"^https?://github\.com/(.+)$"):
        m = re.match(pattern, url)
        if m:
            return f"https://github.com/{m.group(1)}"
    return None


def _task_to_response(task: Task, store: TaskStore | None = None) -> dict:
    """Serialize a Task to a JSON-safe dict.

    store is optional only so call sites that truly have no TaskStore
    handy (none currently) don't break — when given, unmet_dependencies
    is computed for real; without it, dependencies are reported as if
    none were unmet (better than raising, since this is just a display
    field, not enforcement — enforcement lives in TaskStore itself).
    """
    unmet = store.unmet_dependencies(task) if store is not None else []
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "tags": task.tags,
        "project": task.project,
        "review_gate": task.review_gate.value,
        "assigned_to": task.assigned_to,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "acceptance_criteria": task.acceptance_criteria,
        "criteria_met": task.criteria_met,
        "out_of_scope": task.out_of_scope,
        "dependencies": task.dependencies,
        "unmet_dependencies": [{"id": t.id, "title": t.title} for t in unmet],
        "required_credentials": task.required_credentials,
        "steps": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status.value,
                "notes": s.notes,
                "sub_steps": [
                    {"id": ss.id, "title": ss.title, "status": ss.status.value, "notes": ss.notes}
                    for ss in s.sub_steps
                ],
            }
            for s in task.steps
        ],
        "progress": [
            {
                "timestamp": p.timestamp,
                "status": p.status.value,
                "entry": p.entry,
                "actions_taken": p.actions_taken,
                "blocker": {
                    "description": p.blocker.description,
                    "question": p.blocker.question,
                    "options": p.blocker.options,
                    "awaiting": p.blocker.awaiting,
                } if p.blocker else None,
                "resolution": p.resolution,
                "next_step": p.next_step,
                "caller": p.caller,
            }
            for p in task.progress
        ],
    }


# ── HTML templates ───────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-knots cockpit — login</title>
<style>
:root {{
  --bg: #eceef2; --dot: #cdd2db; --card: #ffffff; --card2: #fafbfc;
  --line: #eef0f3; --line2: #dcdfe5; --ink: #23262b; --ink2: #5a6069; --mut: #8a8f99;
  --acc: #6c5ce7; --acc-ink: #ffffff; --err: #e05252;
  --shadow-lg: 0 16px 44px rgba(30, 35, 50, .22);
  --font: 'DM Sans', system-ui, sans-serif; --font-mono: 'DM Mono', monospace;
}}
body[data-theme="dark"] {{
  --bg: #191b20; --dot: #2c3038; --card: #23262d; --card2: #1e2126;
  --line: #2e323a; --line2: #3a3f48; --ink: #dfe2e8; --ink2: #aab0ba; --mut: #767c87;
  --acc: #8f7ff2; --acc-ink: #191b20; --err: #e06a6a;
  --shadow-lg: 0 16px 44px rgba(0, 0, 0, .5);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font: 14px/1.5 var(--font); color: var(--ink); min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  background-color: var(--bg);
  background-image: radial-gradient(var(--dot) 1px, transparent 1px);
  background-size: 22px 22px;
}}
.login-card {{
  width: 380px; max-width: 90vw; background: var(--card); border: 1px solid var(--line);
  border-radius: 16px; box-shadow: var(--shadow-lg); padding: 28px;
}}
.logo {{
  width: 48px; height: 48px; border-radius: 12px; background: var(--card2);
  display: flex; align-items: center; justify-content: center; font-size: 22px;
  margin: 0 auto 14px;
}}
h2 {{ font-size: 17px; font-weight: 700; text-align: center; }}
.sub {{ color: var(--mut); font-size: 12.5px; margin: 6px 0 22px; text-align: center; }}
.sub code {{ font-family: var(--font-mono); background: var(--card2); padding: 1px 5px; border-radius: 4px; }}
label {{ display: block; font-size: 10.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--mut); margin-bottom: 6px; }}
input {{
  width: 100%; padding: 9px 12px; border-radius: 8px; border: 1px solid var(--line2);
  background: var(--card2); color: var(--ink); font-size: 14px; margin-bottom: 16px; font-family: inherit;
}}
input:focus {{ outline: none; border-color: var(--acc); }}
button {{
  width: 100%; padding: 10px; border-radius: 8px; border: none; font-size: 13.5px; font-weight: 700;
  cursor: pointer; background: var(--acc); color: var(--acc-ink); font-family: inherit;
}}
button:hover {{ opacity: 0.9; }}
.error {{ color: var(--err); font-size: 12.5px; margin-bottom: 12px; }}
.note {{ color: var(--mut); font-size: 10.5px; margin-top: 16px; text-align: center; }}
</style>
</head>
<body>
<script>
(function() {{
  var t = localStorage.getItem('agent-knots-theme');
  if (t === 'dark') document.body.setAttribute('data-theme', 'dark');
}})();
</script>
<div class="login-card">
  <div class="logo">&#9889;</div>
  <h2>agent-knots cockpit</h2>
  <p class="sub">Paste the access token printed by<br><code>agent-knots cockpit launch --web</code></p>
  <form method="POST" action="/login">
    <input type="hidden" name="return" value="{return_url}">
    <label>Access token</label>
    <input type="password" name="token" placeholder="Access token" required autofocus>
    <div class="error">{error}</div>
    <button type="submit">Continue</button>
  </form>
  <div class="note">local-only · token stored as a cookie</div>
</div>
</body>
</html>"""

SPA_SHELL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-knots cockpit</title>
<style>
:root {{ --bg: #12141a; --surface: #1c1e26; --surface-raised: #242630; --fg: #e4e4e8; --fg-soft: #a0a0b0; --muted: #6b6b80; --border: #2a2a3a; --running: #9ece6a; --blocked: #e0af68; --assumed: #e0af68; --info: #7aa2f7; --done: #9ece6a; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font: 14px/1.5 system-ui, sans-serif; background: var(--bg); color: var(--fg); height: 100vh; overflow: hidden; }}
#app {{ display: flex; flex-direction: column; height: 100%; }}
.topbar {{ display: flex; align-items: center; gap: 16px; padding: 10px 20px; border-bottom: 1px solid var(--border); background: var(--surface); }}
.topbar-brand {{ font-weight: 700; font-size: 16px; }}
.topbar-nav {{ display: flex; gap: 8px; }}
.topbar-nav a {{ color: var(--fg-soft); text-decoration: none; padding: 4px 10px; border-radius: 4px; font-size: 13px; }}
.topbar-nav a.active {{ background: var(--surface-raised); color: var(--fg); }}
.topbar-stats {{ margin-left: auto; display: flex; gap: 16px; font-size: 13px; color: var(--fg-soft); }}
#agents-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 20px; overflow-y: auto; flex: 1; }}
.agent-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; cursor: pointer; }}
.agent-card:hover {{ border-color: var(--info); }}
.agent-card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.status-pip {{ width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }}
.status-pip.running {{ background: var(--running); box-shadow: 0 0 6px var(--running); animation: glow 2s infinite; }}
@keyframes glow {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:0.6 }} }}
.mode-pill {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 12px; font-size: 11px; background: var(--surface-raised); color: var(--fg-soft); }}
.mode-pill.assumed {{ background: oklch(38% 0.04 75); color: var(--assumed); }}
.agent-card-id {{ font: 12px monospace; color: var(--muted); margin-bottom: 6px; }}
.agent-card-action {{ font-size: 12px; color: var(--fg-soft); }}
.agent-card-stats {{ display: flex; gap: 12px; font-size: 11px; color: var(--muted); margin-top: 8px; }}
.empty-state {{ display: flex; align-items: center; justify-content: center; height: 100%; color: var(--muted); font-size: 16px; }}
</style>
</head>
<body>
<div id="app">
  <div class="topbar">
    <div class="topbar-brand">⚡ agent-knots</div>
    <div class="topbar-nav">
      <a href="#" data-view="overview" class="active">Overview</a>
      <a href="#" data-view="tasks">Tasks</a>
    </div>
    <div class="topbar-stats">
      <span id="stat-agents">0 agents</span>
      <span id="stat-tokens">0 tokens</span>
      <span id="stat-cost">$0.00</span>
    </div>
  </div>
  <div id="agents-grid">
    <div class="empty-state">No agents running. Start one with: agent-knots session start</div>
  </div>
</div>
<script>
// Minimal SPA shell — the full SPA will be built with Vite+React.
// For now, this shell polls /api/agents and renders basic agent cards.
let focusedAgent = null;

async function refresh() {{
  try {{
    const res = await fetch('/api/agents');
    const data = await res.json();
    renderCards(data.agents);
    updateStats(data.agents);
  }} catch(e) {{}}
}}

function renderCards(agents) {{
  const grid = document.getElementById('agents-grid');
  if (!agents.length) {{
    grid.innerHTML = '<div class="empty-state">No agents running. Start one with: agent-knots session start</div>';
    return;
  }}
  grid.innerHTML = agents.map(a => `
    <div class="agent-card" onclick="focusAgent('${{a.id}}')" data-agent-id="${{a.id}}">
      <div class="agent-card-header">
        <div class="status-pip ${{a.running ? 'running' : ''}}"></div>
        <div class="mode-pill ${{a.mode === 'assistant' ? 'assumed' : ''}}">${{a.mode}}</div>
      </div>
      <div class="agent-card-id">${{a.id}}</div>
      <div class="agent-card-action">${{a.running ? 'running...' : 'idle'}}</div>
      <div class="agent-card-stats">
        <span>${{a.tokens_used}} tok</span>
        <span>$${{a.cost_usd.toFixed(2)}}</span>
      </div>
    </div>
  `).join('');
}}

function updateStats(agents) {{
  document.getElementById('stat-agents').textContent = agents.length + ' agent' + (agents.length !== 1 ? 's' : '');
  const tokens = agents.reduce((s,a) => s + a.tokens_used, 0);
  const cost = agents.reduce((s,a) => s + a.cost_usd, 0);
  document.getElementById('stat-tokens').textContent = tokens + ' tokens';
  document.getElementById('stat-cost').textContent = '$' + cost.toFixed(2);
}}

function focusAgent(id) {{
  focusedAgent = id;
  // Will be replaced by React SPA routing
  window.location.hash = '#agent/' + id;
}}

// Poll every 2s.
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
