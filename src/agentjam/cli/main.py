"""agentjam CLI entry point.

All subcommands are registered here. Each subcommand is a separate module
in the cli/ package to keep things manageable as the command set grows.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="agentjam",
    help="Local-first orchestrator for AI coding agents.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the agentjam version."""
    from agentjam import __version__

    typer.echo(f"agentjam {__version__}")


# ---- subcommand groups (stubs for now) ----

session_app = typer.Typer(help="Manage agent sessions.", no_args_is_help=True)
cockpit_app = typer.Typer(help="Launch monitoring surfaces.", no_args_is_help=True)
vault_app = typer.Typer(help="Manage the encrypted credential vault.", no_args_is_help=True)
project_app = typer.Typer(help="Manage projects (multi-repo workspaces).", no_args_is_help=True)
task_app = typer.Typer(help="Manage structured tasks.", no_args_is_help=True)
settings_app = typer.Typer(help="View and change global settings.", no_args_is_help=True)

app.add_typer(session_app, name="session")
app.add_typer(cockpit_app, name="cockpit")
app.add_typer(vault_app, name="vault")
app.add_typer(project_app, name="project")
app.add_typer(task_app, name="task")
app.add_typer(settings_app, name="settings")


# ---- session commands ----

@session_app.command()
def start(
    task: str = typer.Option(None, "--task", help="Task ID to assign."),
    project: str = typer.Option(None, "--project", help="Project ID."),
    mode: str = typer.Option("agent", "--mode", help="Agent mode (agent, assistant, reviewer, security)."),
    detach: bool = typer.Option(False, "--detach", help="Run in background and return immediately."),
    worktree: bool = typer.Option(False, "--worktree", help="Create a git worktree for this session."),
    driver: str = typer.Option("strands", "--driver", help="Agent driver (strands)."),
) -> None:
    """Start a new agent session."""
    typer.echo(f"Starting session (task={task}, project={project}, mode={mode}, detach={detach})...")
    typer.echo("Not yet implemented.")


@session_app.command(name="list")
def list_sessions() -> None:
    """List all sessions."""
    typer.echo("Not yet implemented.")


@session_app.command()
def show(session_id: str = typer.Argument(..., help="Session ID.")) -> None:
    """Show details for a session."""
    typer.echo(f"Session: {session_id}")
    typer.echo("Not yet implemented.")


@session_app.command()
def stop(session_id: str = typer.Argument(..., help="Session ID.")) -> None:
    """Stop a running session."""
    typer.echo(f"Stopping session: {session_id}")
    typer.echo("Not yet implemented.")


@session_app.command()
def logs(session_id: str = typer.Argument(..., help="Session ID.")) -> None:
    """Stream logs from a running session."""
    typer.echo(f"Streaming logs for: {session_id}")
    typer.echo("Not yet implemented.")


# ---- cockpit commands ----

@cockpit_app.command()
def launch(
    web: bool = typer.Option(False, "--web", help="Launch the web GUI instead of TUI."),
) -> None:
    """Launch the cockpit (TUI by default, --web for browser GUI)."""
    if web:
        typer.echo("Launching web cockpit...")
        typer.echo("Not yet implemented.")
    else:
        typer.echo("Launching TUI cockpit...")
        typer.echo("Not yet implemented.")


# ---- vault commands ----

@vault_app.command()
def init() -> None:
    """Initialize a new vault."""
    typer.echo("Initializing vault...")
    typer.echo("Not yet implemented.")


@vault_app.command()
def unlock() -> None:
    """Unlock the vault with a passphrase."""
    typer.echo("Unlocking vault...")
    typer.echo("Not yet implemented.")


@vault_app.command()
def lock() -> None:
    """Lock the vault."""
    typer.echo("Locking vault...")
    typer.echo("Not yet implemented.")


@vault_app.command()
def status() -> None:
    """Show vault status (locked/unlocked, entry count)."""
    typer.echo("Vault status not yet implemented.")


# ---- project commands ----

@project_app.command(name="list")
def list_projects() -> None:
    """List all projects."""
    typer.echo("Not yet implemented.")


# ---- task commands ----

@task_app.command(name="list")
def list_tasks() -> None:
    """List all tasks."""
    typer.echo("Not yet implemented.")


# ---- settings commands ----

@settings_app.command()
def show() -> None:
    """Show current settings."""
    typer.echo("Not yet implemented.")


if __name__ == "__main__":
    app()
