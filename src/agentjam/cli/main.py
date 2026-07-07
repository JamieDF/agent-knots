"""agentjam CLI entry point.

All subcommands are registered here. Commands are wired to the real
implementations (VaultStore, SessionManager, cockpit) where ready,
and print stubs where still in progress.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from agentjam.config import (
    cockpit_token_file,
    sessions_dir,
    tasks_dir,
    projects_dir,
    vault_dir,
)
from agentjam.session.manager import SessionManager
from agentjam.vault.store import LockState, VaultStore

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


# ── subcommand groups ────────────────────────────────────────────────────────

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


# ── session commands ─────────────────────────────────────────────────────────


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
      2. Environment variables AGENTJAM_API_KEY, AGENTJAM_MODEL, AGENTJAM_BASE_URL
      3. Settings file ~/.agentjam/settings.yaml

    For MiniMax:
      export AGENTJAM_MODEL=openai/minimax-m2.7
      export AGENTJAM_BASE_URL=https://api.minimax.io/v1
      export AGENTJAM_API_KEY=<your-key>

    Then run: agentjam session start --prompt "your task"
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

    if session.running:
        typer.echo("Agent is running. Use 'agentjam cockpit' to monitor.")
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


# ── cockpit commands ─────────────────────────────────────────────────────────


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

    from agentjam.cockpit.web.auth import load_or_create_token
    from agentjam.cockpit.web.server import create_app

    mgr = SessionManager(sessions_dir())

    # Check for static build.
    static_dir = Path(__file__).parent.parent.parent.parent.parent / "frontend" / "dist"
    if not static_dir.exists():
        typer.echo("Warning: frontend not built. Run: cd frontend && npm run build")
        typer.echo("Serving inline SPA shell instead.")
        static_dir = None

    web_app = create_app(mgr, static_dir=static_dir)
    token = load_or_create_token(cockpit_token_file())

    typer.echo(f"⚡ agentjam cockpit (web): http://{host}:{port}/?token={token}")
    typer.echo("Press Ctrl-C to stop.")

    uvicorn.run(web_app, host=host, port=port, log_level="warning")


def _launch_tui() -> None:
    """Launch the Textual TUI cockpit."""
    from agentjam.cockpit.tui.app import CockpitApp

    mgr = SessionManager(sessions_dir())
    app = CockpitApp(mgr)
    app.run()


# ── vault commands ───────────────────────────────────────────────────────────

# Store a global reference so subcommands can access the same store.
_vault_store: VaultStore | None = None


def _get_vault() -> VaultStore:
    global _vault_store
    if _vault_store is None:
        _vault_store = VaultStore(vault_dir())
    return _vault_store


@vault_app.command()
def init() -> None:
    """Initialize a new vault with a passphrase."""
    store = _get_vault()
    if store.lock_state == LockState.UNLOCKED:
        typer.echo("Vault is already initialized and unlocked.")
        return
    if store.lock_state == LockState.LOCKED:
        typer.echo("Vault is already initialized but locked. Use 'vault unlock'.")
        return

    passphrase = typer.prompt("Choose a passphrase", hide_input=True)
    confirm = typer.prompt("Confirm passphrase", hide_input=True)
    if passphrase != confirm:
        typer.echo("Passphrases do not match.")
        raise typer.Exit(1)

    store.unlock(passphrase)
    typer.echo("Vault initialized and unlocked.")


@vault_app.command()
def unlock() -> None:
    """Unlock the vault with a passphrase."""
    store = _get_vault()
    if store.lock_state == LockState.UNLOCKED:
        typer.echo("Vault is already unlocked.")
        return
    if store.lock_state == LockState.UNINITIALIZED:
        typer.echo("Vault is not initialized. Use 'vault init' first.")
        raise typer.Exit(1)

    passphrase = typer.prompt("Passphrase", hide_input=True)
    try:
        store.unlock(passphrase)
        typer.echo("Vault unlocked.")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)


@vault_app.command()
def lock() -> None:
    """Lock the vault."""
    store = _get_vault()
    if store.lock_state != LockState.UNLOCKED:
        typer.echo("Vault is not unlocked.")
        return
    store.lock()
    typer.echo("Vault locked.")


@vault_app.command()
def status() -> None:
    """Show vault status."""
    store = _get_vault()
    state = store.lock_state.value
    count = len(store.list_credentials())
    typer.echo(f"Status: {state}")
    typer.echo(f"Credentials: {count}")


@vault_app.command()
def add(
    cred_id: str = typer.Argument(..., help="Credential ID (e.g. 'github/work')."),
    value: str = typer.Option(..., "--value", help="The secret value.", prompt=True, hide_input=True),
    description: str = typer.Option("", "--description", help="Human-readable note."),
    tag: list[str] = typer.Option([], "--tag", help="Tags for this credential (repeatable)."),
) -> None:
    """Add a new credential to the vault."""
    from agentjam.vault.store import Credential

    store = _get_vault()
    if store.lock_state != LockState.UNLOCKED:
        typer.echo("Vault is locked. Use 'vault unlock' first.")
        raise typer.Exit(1)

    try:
        store.add_credential(Credential(
            id=cred_id,
            value=value,
            description=description,
            tags=list(tag),
        ))
        typer.echo(f"Credential '{cred_id}' added.")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)


@vault_app.command(name="list")
def list_credentials() -> None:
    """List all credentials in the vault (without values)."""
    store = _get_vault()
    creds = store.list_credentials()
    if not creds:
        typer.echo("No credentials stored.")
        return
    for c in creds:
        tags = ", ".join(c.tags) if c.tags else ""
        typer.echo(f"  {c.id:30s}  uses={c.uses_total:>4d}  {tags}")


@vault_app.command()
def show(cred_id: str = typer.Argument(..., help="Credential ID.")) -> None:
    """Show a credential's value (requires unlocked vault)."""
    store = _get_vault()
    if store.lock_state != LockState.UNLOCKED:
        typer.echo("Vault is locked. Use 'vault unlock' first.")
        raise typer.Exit(1)

    try:
        value = store.use_credential(cred_id, caller="user")
        typer.echo(value)
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)


@vault_app.command()
def remove(cred_id: str = typer.Argument(..., help="Credential ID to remove.")) -> None:
    """Remove a credential from the vault."""
    store = _get_vault()
    if store.lock_state != LockState.UNLOCKED:
        typer.echo("Vault is locked. Use 'vault unlock' first.")
        raise typer.Exit(1)

    try:
        store.remove_credential(cred_id)
        typer.echo(f"Credential '{cred_id}' removed.")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)


@vault_app.command()
def audit(
    cred_id: str = typer.Option("", "--credential", help="Filter by credential ID."),
    limit: int = typer.Option(0, "--limit", help="Max entries to show."),
) -> None:
    """Show the audit log."""
    from agentjam.vault.store import AuditOptions

    store = _get_vault()
    entries = store.audit_log(AuditOptions(credential=cred_id, limit=limit))
    if not entries:
        typer.echo("No audit entries.")
        return
    for e in entries:
        status = "✓" if e.success else "✗"
        ts = _format_ts(e.timestamp)
        typer.echo(f"  {ts}  {status}  {e.credential:25s}  {e.caller:15s}  {e.template}")


def _format_ts(ts: float) -> str:
    import datetime
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ── project commands ─────────────────────────────────────────────────────────


@project_app.command(name="list")
def list_projects() -> None:
    """List all projects."""
    typer.echo("Not yet implemented.")


# ── task commands ────────────────────────────────────────────────────────────


@task_app.command(name="list")
def list_tasks() -> None:
    """List all tasks."""
    typer.echo("Not yet implemented.")


# ── settings commands ────────────────────────────────────────────────────────


@settings_app.command()
def show() -> None:
    """Show current settings."""
    typer.echo("Not yet implemented.")


if __name__ == "__main__":
    app()
