"""FastAPI web cockpit server.

Serves:
  - Static SPA assets (Vite build output)
  - REST API for session management
  - SSE endpoint for live event streaming
  - Token-based authentication
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI


def create_app(static_dir: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        static_dir: Path to the Vite build output directory. If None,
                    static file serving is disabled (dev mode).
    """
    app = FastAPI(title="agentjam cockpit")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
