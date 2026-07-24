"""`agent-knots cockpit` subcommands."""

from __future__ import annotations

from pathlib import Path

import typer

from agent_knots.config import cockpit_token_file, sessions_dir
from agent_knots.session.manager import SessionManager

cockpit_app = typer.Typer(help="Launch monitoring surfaces.", no_args_is_help=True)


@cockpit_app.command()
def launch(
    web: bool = typer.Option(False, "--web", help="Launch the web GUI instead of TUI."),
    port: int = typer.Option(8080, "--port", help="Port for the web server."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
) -> None:
    """Launch the cockpit (TUI by default, --web for browser GUI)."""
    if web:
        _launch_web(host, port)
    else:
        _launch_tui()


def _launch_web(host: str, port: int) -> None:
    """Launch the FastAPI web cockpit."""
    import uvicorn

    from agent_knots import settings
    from agent_knots.session.runtime import set_runtime_type
    from agent_knots.cockpit.web.auth import load_or_create_token
    from agent_knots.cockpit.web.server import create_app

    s = settings.load()
    set_runtime_type(s.agent.runtime)

    mgr = SessionManager(sessions_dir())

    # __file__ is src/agent_knots/cli/cockpit.py → 4 parents up = project root.
    static_dir = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if not static_dir.exists():
        typer.echo("Warning: frontend not built. Run: cd frontend && npm run build")
        typer.echo("Serving inline SPA shell instead.")
        static_dir = None

    web_app = create_app(mgr, static_dir=static_dir)
    token = load_or_create_token(cockpit_token_file())

    typer.echo(f"⚡ agent-knots cockpit (web): http://{host}:{port}/?token={token}")
    typer.echo("Press Ctrl-C to stop.")

    uvicorn.run(web_app, host=host, port=port, log_level="warning")


def _launch_tui() -> None:
    """Launch the Textual TUI cockpit."""
    from agent_knots.cockpit.tui.app import CockpitApp

    mgr = SessionManager(sessions_dir())
    app = CockpitApp(mgr)
    app.run()
