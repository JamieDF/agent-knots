"""agent-knots CLI entry point.

Wires together the five subcommand groups, each defined in its own
module (session.py, vault.py, project.py, task.py, settings.py), plus
the top-level `launch` command (the TUI/web cockpit entry point — not
its own subcommand group, since it was only ever one command).
Commands are wired to the real implementations (VaultStore,
SessionManager, cockpit) where ready, and print stubs where still in
progress.
"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_knots.cli.playground import playground_app
from agent_knots.cli.project import project_app
from agent_knots.cli.session import session_app
from agent_knots.cli.settings import settings_app
from agent_knots.cli.task import task_app
from agent_knots.cli.vault import vault_app
from agent_knots.config import cockpit_token_file, sessions_dir, vault_dir
from agent_knots.session.manager import SessionManager
from agent_knots.vault.store import VaultStore

app = typer.Typer(
    name="agent-knots",
    help="Local-first orchestrator for AI coding agents.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the agent-knots version."""
    from agent_knots import __version__

    typer.echo(f"agent-knots {__version__}")


@app.command()
def launch(
    tui: bool = typer.Option(False, "--tui", help="Launch the terminal UI instead of the web GUI."),
    web: bool = typer.Option(True, "--web", help="Launch the web GUI (default)."),
    port: int = typer.Option(8080, "--port", help="Port for the web server."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
) -> None:
    """Launch the cockpit (web GUI by default, --tui for the terminal UI)."""
    if tui:
        _launch_tui()
    else:
        _launch_web(host, port)


def _launch_web(host: str, port: int) -> None:
    """Launch the FastAPI web cockpit."""
    import uvicorn

    from agent_knots import settings
    from agent_knots.cockpit.web.auth import load_or_create_token
    from agent_knots.cockpit.web.server import create_app
    from agent_knots.session.runtime import set_runtime_type

    s = settings.load()
    set_runtime_type(s.agent.runtime)

    # One VaultStore instance shared with the web app's vault router — a
    # second instance here would mean unlocking via the Settings UI never
    # unlocks the store agent sessions actually read from.
    mgr = SessionManager(sessions_dir(), vault=VaultStore(vault_dir()))

    # __file__ is src/agent_knots/cli/main.py → 4 parents up = project root.
    static_dir = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if not static_dir.exists():
        typer.echo("Warning: frontend not built. Run: cd frontend && npm run build")
        typer.echo("Serving inline SPA shell instead.")
        static_dir = None

    web_app = create_app(mgr, static_dir=static_dir)
    token = load_or_create_token(cockpit_token_file())

    typer.echo(f"agent-knots (web): http://{host}:{port}/?token={token}")
    typer.echo("Press Ctrl-C to stop.")

    uvicorn.run(web_app, host=host, port=port, log_level="warning")


def _launch_tui() -> None:
    """Launch the Textual TUI cockpit."""
    from agent_knots.cockpit.tui.app import CockpitApp

    mgr = SessionManager(sessions_dir(), vault=VaultStore(vault_dir()))
    app = CockpitApp(mgr)
    app.run()


app.add_typer(session_app, name="session")
app.add_typer(vault_app, name="vault")
app.add_typer(project_app, name="project")
app.add_typer(task_app, name="task")
app.add_typer(settings_app, name="settings")
app.add_typer(playground_app, name="playground")


if __name__ == "__main__":
    app()
