"""`agent-knots session` subcommands."""

from __future__ import annotations

import asyncio

import typer

from agent_knots.config import sessions_dir
from agent_knots.session.manager import SessionManager

session_app = typer.Typer(help="Manage agent sessions.", no_args_is_help=True)


@session_app.command()
def start(
    task: str = typer.Option(None, "--task", help="Task ID to assign."),
    project: str = typer.Option(None, "--project", help="Project ID."),
    mode: str = typer.Option("agent", "--mode", help="Agent mode (agent, assistant)."),
    detach: bool = typer.Option(False, "--detach", help="Run in background."),
    model: str = typer.Option("", "--model", help="Model override (e.g. openai/minimax-m2.7)."),
    api_key: str = typer.Option("", "--api-key", help="API key override."),
    base_url: str = typer.Option("", "--base-url", help="Custom API base URL (e.g. for MiniMax)."),
    prompt: str = typer.Option(None, "--prompt", help="Initial task description."),
) -> None:
    """Start a new agent session.

    The API key and model are resolved from (in order):
      1. CLI flags --api-key, --model, --base-url
      2. Environment variables AGENT_KNOTS_API_KEY, AGENT_KNOTS_MODEL, AGENT_KNOTS_BASE_URL
      3. Settings file ~/.agent-knots/settings.yaml

    For MiniMax:
      export AGENT_KNOTS_MODEL=openai/minimax-m2.7
      export AGENT_KNOTS_BASE_URL=https://api.minimax.io/v1
      export AGENT_KNOTS_API_KEY=<your-key>

    Then run: agent-knots session start --prompt "your task"
    """
    if detach:
        typer.echo("Detached mode not yet implemented.")
        raise typer.Exit(1)

    mgr = SessionManager(sessions_dir())

    try:
        session = asyncio.run(mgr.start(
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            mode=mode,
            task_id=task,
            project_id=project,
            task_description=prompt,
        ))
    except RuntimeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)

    typer.echo(f"Session started: {session.id}")
    typer.echo(f"Mode: {session.mode}")
    if task:
        typer.echo(f"Task: {task}")

    if session.running:
        typer.echo("Agent is running. Use 'agent-knots launch' to monitor.")
    else:
        typer.echo("Session created but not started (no --prompt given).")


@session_app.command(name="list")
def list_sessions() -> None:
    """List all active sessions."""
    mgr = SessionManager(sessions_dir())
    agents = mgr.active
    if not agents:
        typer.echo("No active sessions.")
        return
    for a in agents:
        status = "running" if a.running else "idle"
        typer.echo(f"  {a.id}  {a.mode:10s}  {status:8s}  {a.tokens_used:>6d} tok  ${a.cost_usd:.3f}")
