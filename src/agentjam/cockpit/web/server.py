"""FastAPI web cockpit server.

Serves:
  - Static SPA assets (Vite build output, or inline HTML in dev mode)
  - REST API for session management
  - SSE endpoint for live event streaming
  - Token-based authentication
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentjam.cockpit.web.auth import Auth, COOKIE_NAME, load_or_create_token
from agentjam.config import cockpit_token_file, tasks_dir
from agentjam.events import Event, EventType
from agentjam.session.manager import Session, SessionManager
from agentjam import settings
from agentjam.task.store import TaskStore
from agentjam.task.models import Task, TaskStatus, Priority, new_task_id


# ── request models (module-level so FastAPI can resolve them) ────────────────


class SaveSettingsRequest(BaseModel):
    default_model: str = "openai/gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    default_mode: str = "agent"


class CreateSessionRequest(BaseModel):
    prompt: str = ""
    mode: str = "agent"
    task_id: str | None = None
    project_id: str | None = None


# ── app factory ──────────────────────────────────────────────────────────────


def create_app(
    session_manager: SessionManager,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        session_manager: The session manager to query for agents.
        static_dir: Path to the Vite build output directory. If None,
                    inline HTML is served (dev mode).
    """
    app = FastAPI(title="agentjam cockpit")

    auth = Auth(cockpit_token_file())

    # ── auth middleware ──────────────────────────────────────────────────

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """Authenticate all requests except /login, /api/health, and static files."""
        path = request.url.path
        # Allow login, health, and static assets without auth.
        if path in ("/login", "/api/health") or path.startswith("/assets/"):
            return await call_next(request)
        # Allow SSE with ?token= query param for EventSource (can't set headers).
        if path.startswith("/api/") and request.query_params.get("token"):
            token = request.query_params.get("token", "")
            if token == auth.token:
                return await call_next(request)
        # Everything else requires the cookie.
        cookie = request.cookies.get(COOKIE_NAME, "")
        if not cookie or cookie != auth.token:
            # HTMX requests get 401, browser gets redirect to login.
            if request.headers.get("HX-Request"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse(url="/login?return=" + request.url.path, status_code=303)
        return await call_next(request)

    # ── login ────────────────────────────────────────────────────────────

    @app.get("/login")
    async def login_page(request: Request, return_url: str = Query("/", alias="return")):
        return HTMLResponse(LOGIN_HTML.format(
            return_url=return_url or "/",
            error="",
        ))

    @app.post("/login")
    async def login_post(token: str = Form(...), return_url: str = Form("/")):
        if token != auth.token:
            return HTMLResponse(LOGIN_HTML.format(
                return_url=return_url,
                error="Invalid token.",
            ))
        response = RedirectResponse(url=return_url or "/", status_code=303)
        response.set_cookie(
            key=COOKIE_NAME,
            value=auth.token,
            httponly=True,
            samesite="strict",
            max_age=7 * 24 * 3600,
        )
        return response

    # ── SPA shell ────────────────────────────────────────────────────────

    @app.get("/")
    async def index():
        """Serve the SPA shell. In prod mode, this is the Vite-built index.html."""
        if static_dir and (static_dir / "index.html").exists():
            return HTMLResponse((static_dir / "index.html").read_text())
        return HTMLResponse(SPA_SHELL_HTML)

    # ── REST API ─────────────────────────────────────────────────────────

    @app.get("/api/agents")
    async def list_agents():
        """Return all active sessions as JSON."""
        sessions = session_manager.active
        return {
            "agents": [
                {
                    "id": s.id,
                    "mode": s.mode,
                    "task_id": s.task_id,
                    "project_id": s.project_id,
                    "tokens_used": s.tokens_used,
                    "cost_usd": s.cost_usd,
                    "running": s.running,
                }
                for s in sessions
            ]
        }

    @app.get("/api/agent/{agent_id}/events")
    async def agent_events(agent_id: str, request: Request):
        """SSE endpoint for live agent events."""
        session = session_manager.get(agent_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        async def event_generator():
            # Send initial connection event.
            yield "event: connected\ndata: {}\n\n"

            try:
                while True:
                    # Check if client disconnected.
                    if await request.is_disconnected():
                        break

                    try:
                        event = await asyncio.wait_for(
                            session.event_stream.get(), timeout=15.0
                        )
                    except asyncio.TimeoutError:
                        # Send keepalive.
                        yield ": keepalive\n\n"
                        continue

                    event_html = format_event_html(event)
                    yield f"data: {json.dumps({'html': event_html, 'type': event.type.value, 'session_id': event.session_id})}\n\n"

            except asyncio.CancelledError:
                pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

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

    @app.post("/api/agent/{agent_id}/send")
    async def agent_send(agent_id: str, message: str = Form(...)):
        """Send a message to an agent."""
        await session_manager.send(agent_id, message)
        return {"status": "ok"}

    # ── settings API ─────────────────────────────────────────────────────

    @app.get("/api/settings")
    async def get_settings():
        """Return current settings (API key masked)."""
        s = settings.load()
        return {
            "configured": settings.is_configured(),
            "agent": {
                "default_model": s.agent.default_model,
                "api_key": settings.mask_key(s.agent.api_key),
                "base_url": s.agent.base_url,
                "default_mode": s.agent.default_mode,
            },
        }

    @app.put("/api/settings")
    async def save_settings(body: SaveSettingsRequest):
        """Save settings. If api_key is all asterisks, preserve existing key."""
        s = settings.load()
        s.agent.default_model = body.default_model
        s.agent.base_url = body.base_url
        s.agent.default_mode = body.default_mode

        # Only update API key if a real value was provided (not masked).
        if body.api_key and "..." not in body.api_key and not body.api_key.startswith("****"):
            s.agent.api_key = body.api_key

        settings.save(s)
        return {"status": "ok", "configured": settings.is_configured()}

    # ── session management API ────────────────────────────────────────────

    @app.post("/api/sessions")
    async def create_session(body: CreateSessionRequest):
        """Start a new agent session in the background."""
        if not settings.is_configured():
            raise HTTPException(status_code=400, detail="Settings not configured. Run setup first.")

        s = settings.load()
        try:
            session = await session_manager.start(
                model=s.agent.default_model,
                api_key=s.agent.api_key,
                base_url=s.agent.base_url or None,
                mode=body.mode,
                task_id=body.task_id,
                project_id=body.project_id,
                task_description=body.prompt,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

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
        return _task_to_response(task)

    class CreateTaskRequest(BaseModel):
        title: str
        description: str = ""
        priority: str = "medium"
        project: str = ""
        tags: list[str] = []
        acceptance_criteria: list[str] = []

    @app.post("/api/tasks")
    async def create_task(body: CreateTaskRequest):
        """Create a new task."""
        store = TaskStore(tasks_dir())
        task = Task(
            id=new_task_id(body.project),
            title=body.title,
            description=body.description,
            priority=Priority(body.priority),
            project=body.project,
            tags=body.tags,
            acceptance_criteria=body.acceptance_criteria,
        )
        store.create(task)
        return _task_to_response(task)

    class UpdateTaskRequest(BaseModel):
        title: str | None = None
        status: str | None = None
        priority: str | None = None
        assign: str | None = None

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, body: UpdateTaskRequest):
        """Update a task's status, priority, or assignment."""
        store = TaskStore(tasks_dir())
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        if body.status:
            task = store.set_status(task_id, TaskStatus(body.status))
        if body.priority:
            task.priority = Priority(body.priority)
            task = store.update(task)
        if body.title:
            task.title = body.title
            task = store.update(task)
        if body.assign is not None:
            task = store.assign(task_id, body.assign)

        return _task_to_response(task)

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str):
        """Delete a task."""
        store = TaskStore(tasks_dir())
        try:
            store.delete(task_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "ok"}

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "agents": len(session_manager.active)}

    # ── static files (prod mode) ─────────────────────────────────────────

    if static_dir and static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    return app


# ── event HTML formatting ────────────────────────────────────────────────────


def format_event_html(event: Event) -> str:
    """Format an agentjam Event as an HTML snippet for the cockpit.

    Matches the Go implementation's formatEventHTML, producing the same
    CSS class structure used by the SPA.
    """
    ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))

    if event.type == EventType.MESSAGE:
        return (
            f'<div class="prose-row">'
            f'<div class="prose-avatar agent">A</div>'
            f'<div class="prose-content">'
            f'<div class="prose-text">{_escape(event.message)}</div>'
            f'</div>'
            f'<div class="prose-ts">{ts}</div>'
            f'</div>'
        )

    if event.type == EventType.THINKING:
        return (
            f'<div class="prose-row prose-thinking">'
            f'<div class="prose-avatar thinking">T</div>'
            f'<div class="prose-content">'
            f'<div class="prose-text">{_escape(event.message)}</div>'
            f'</div>'
            f'<div class="prose-ts">{ts}</div>'
            f'</div>'
        )

    if event.type == EventType.TOOL_CALL and event.tool_call:
        icon = _tool_icon(event.tool_call.name)
        args = _format_args(event.tool_call.args)
        return (
            f'<div class="tool-card">'
            f'<div class="tool-header"><span class="tool-icon">{icon}</span>'
            f'<span class="tool-name">{event.tool_call.name}</span></div>'
            f'<div class="tool-args">{_escape(args)}</div>'
            f'</div>'
        )

    if event.type == EventType.TOOL_RESULT:
        return (
            f'<div class="prose-row">'
            f'<div class="prose-avatar" style="color:var(--done)">&#10003;</div>'
            f'<div class="prose-content">'
            f'<div class="prose-text" style="color:var(--muted);font-size:12px">'
            f'{_escape(event.message[:200])}</div>'
            f'</div>'
            f'<div class="prose-ts">{ts}</div>'
            f'</div>'
        )

    if event.type == EventType.BLOCKER:
        return (
            f'<div class="prose-row prose-blocker">'
            f'<div class="prose-avatar" style="color:var(--assumed)">?</div>'
            f'<div class="prose-content">'
            f'<div class="prose-text">{_escape(event.message)}</div>'
            f'</div>'
            f'<div class="prose-ts">{ts}</div>'
            f'</div>'
        )

    if event.type == EventType.ERROR:
        return (
            f'<div class="prose-row prose-error">'
            f'<div class="prose-avatar" style="color:var(--blocked)">!</div>'
            f'<div class="prose-content">'
            f'<div class="prose-text" style="color:var(--blocked)">{_escape(event.error or event.message)}</div>'
            f'</div>'
            f'<div class="prose-ts">{ts}</div>'
            f'</div>'
        )

    if event.type == EventType.STATE_CHANGE:
        return (
            f'<div class="prose-row prose-state">'
            f'<div class="prose-avatar" style="color:var(--info)">⚡</div>'
            f'<div class="prose-content">'
            f'<div class="prose-text" style="color:var(--muted);font-size:12px">{_escape(event.message)}</div>'
            f'</div>'
            f'<div class="prose-ts">{ts}</div>'
            f'</div>'
        )

    # Default / unknown.
    return (
        f'<div class="prose-row">'
        f'<div class="prose-content">'
        f'<div class="prose-text" style="color:var(--muted)">{_escape(event.message)}</div>'
        f'</div>'
        f'<div class="prose-ts">{ts}</div>'
        f'</div>'
    )


def _tool_icon(name: str) -> str:
    """Return an icon for a tool name."""
    icons = {
        "bash": "▶",
        "shell": "▶",
        "read": "R",
        "read_file": "R",
        "edit": "E",
        "edit_file": "E",
        "write": "W",
        "write_file": "W",
    }
    return icons.get(name, "●")


def _format_args(args: dict) -> str:
    """Format tool arguments for display, truncated."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)


def _escape(text: str) -> str:
    """Basic HTML escaping."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _task_to_response(task: Task) -> dict:
    """Serialize a Task to a JSON-safe dict."""
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "tags": task.tags,
        "project": task.project,
        "assigned_to": task.assigned_to,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "acceptance_criteria": task.acceptance_criteria,
        "out_of_scope": task.out_of_scope,
        "dependencies": task.dependencies,
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
<title>agentjam cockpit — login</title>
<style>
:root {{ --bg: #12141a; --surface: #1c1e26; --fg: #e4e4e8; --fg-soft: #a0a0b0; --muted: #6b6b80; --border: #2a2a3a; --info: #7aa2f7; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font: 14px/1.5 system-ui, sans-serif; background: var(--bg); color: var(--fg); min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
.login-box {{ width: 380px; }}
h2 {{ font-size: 22px; font-weight: 600; margin-bottom: 20px; }}
label {{ display: block; font-size: 13px; color: var(--fg-soft); margin-bottom: 6px; }}
input {{ width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--fg); font-size: 15px; margin-bottom: 16px; }}
input:focus {{ outline: none; border-color: var(--info); }}
button {{ width: 100%; padding: 10px; border-radius: 8px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; background: var(--fg); color: var(--bg); }}
button:hover {{ opacity: 0.88; }}
.error {{ color: #f7768e; font-size: 13px; margin-bottom: 12px; }}
</style>
</head>
<body>
<div class="login-box">
  <h2>&#9889; agentjam cockpit</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:20px">Enter your access token.</p>
  <form method="POST" action="/login">
    <input type="hidden" name="return" value="{return_url}">
    <label>Token</label>
    <input type="password" name="token" placeholder="Access token" required autofocus>
    <div class="error">{error}</div>
    <button type="submit">Connect</button>
  </form>
</div>
</body>
</html>"""

SPA_SHELL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agentjam cockpit</title>
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
    <div class="topbar-brand">⚡ agentjam</div>
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
    <div class="empty-state">No agents running. Start one with: agentjam session start</div>
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
    grid.innerHTML = '<div class="empty-state">No agents running. Start one with: agentjam session start</div>';
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
