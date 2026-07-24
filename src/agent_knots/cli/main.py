"""agent-knots CLI entry point.

Wires together the six subcommand groups, each defined in its own
module (session.py, cockpit.py, vault.py, project.py, task.py,
settings.py). Commands are wired to the real implementations
(VaultStore, SessionManager, cockpit) where ready, and print stubs
where still in progress.
"""

from __future__ import annotations

import typer

from agent_knots.cli.cockpit import cockpit_app
from agent_knots.cli.project import project_app
from agent_knots.cli.session import session_app
from agent_knots.cli.settings import settings_app
from agent_knots.cli.task import task_app
from agent_knots.cli.vault import vault_app

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


app.add_typer(session_app, name="session")
app.add_typer(cockpit_app, name="cockpit")
app.add_typer(vault_app, name="vault")
app.add_typer(project_app, name="project")
app.add_typer(task_app, name="task")
app.add_typer(settings_app, name="settings")


if __name__ == "__main__":
    app()
