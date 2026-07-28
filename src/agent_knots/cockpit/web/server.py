"""FastAPI web cockpit server.

Serves:
  - Static SPA assets (Vite build output, or inline HTML in dev mode)
  - REST API for session management (routes/*.py, one module per domain)
  - SSE endpoint for live event streaming
  - Token-based authentication

This module is just the composition root: auth middleware, login,
the SPA shell/fallback, and wiring each domain's APIRouter together.
The actual route handlers live in routes/{agents,tasks,workspaces,
settings,vault,mcp,tools,workflows,review,fs}.py.
"""

from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agent_knots.cockpit.web.auth import Auth, COOKIE_NAME, verify_token
from agent_knots.cockpit.web.htmltemplates import LOGIN_HTML, SPA_SHELL_HTML
from agent_knots.cockpit.web.routes import (
    agents, fs, mcp, review, settings as settings_routes, tasks, tools, vault as vault_routes,
    workflows, workspaces,
)
from agent_knots.config import cockpit_token_file, vault_dir
from agent_knots.session.manager import SessionManager
from agent_knots.vault.store import VaultStore


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
    app = FastAPI(title="agent-knots")

    auth = Auth(cockpit_token_file())

    # Reuse session_manager.vault rather than building a second
    # VaultStore here: unlock state (the derived key) lives in memory on
    # the instance itself, so two instances would mean unlocking via
    # this router never unlocks the store agent sessions actually read
    # credentials from. Falls back to a fresh instance only when the
    # manager wasn't given one (e.g. tests constructing SessionManager
    # directly with no vault).
    vault = session_manager.vault or VaultStore(vault_dir())

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

    app.include_router(agents.create_router(session_manager, auth))
    app.include_router(tasks.create_router(session_manager))
    app.include_router(workspaces.create_router())
    app.include_router(settings_routes.create_router())
    app.include_router(vault_routes.create_router(vault))
    app.include_router(mcp.create_router())
    app.include_router(tools.create_router())
    app.include_router(workflows.create_router())
    app.include_router(review.create_router())
    app.include_router(fs.create_router())

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
    #
    # Vite copies everything in frontend/public/ (favicon.svg,
    # favicon.ico, site.webmanifest, apple-touch-icon.png, etc.) to the
    # *root* of dist/, not into dist/assets/ — only /assets was ever
    # mounted as StaticFiles, so any request for one of these root-level
    # files fell through to this fallback and got the SPA HTML shell
    # back instead of the real file (the browser then silently fails to
    # render it as a favicon/icon/manifest). Check for a real file in
    # static_dir first; only fall back to the SPA shell if there isn't
    # one. resolve() + relative_to() confines this to static_dir itself
    # — full_path comes straight from the client, so a bare `static_dir /
    # full_path` without resolving could otherwise serve anything on
    # disk via a `../../..` path.
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("assets/"):
            raise HTTPException(status_code=404, detail="Not found")
        if static_dir and full_path:
            candidate = (static_dir / full_path).resolve()
            try:
                candidate.relative_to(static_dir.resolve())
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                return FileResponse(candidate)
        return HTMLResponse(_spa_html())

    return app
