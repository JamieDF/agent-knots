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
from agentjam.task.models import Priority, Task, TaskStatus
from agentjam.task.store import TaskStore
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
    if task:
        typer.echo(f"Task: {task}")

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

    from agentjam import settings
    from agentjam.session.runtime import set_runtime_type
    from agentjam.cockpit.web.auth import load_or_create_token
    from agentjam.cockpit.web.server import create_app

    s = settings.load()
    set_runtime_type(s.agent.runtime)

    mgr = SessionManager(sessions_dir())

    # Check for static build.
    # __file__ is src/agentjam/cli/main.py → 4 parents up = project root.
    static_dir = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
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
    value: str = typer.Option("", "--value", help="The secret value. If omitted, you'll be prompted."),
    description: str = typer.Option("", "--description", help="Human-readable note."),
    tag: list[str] = typer.Option([], "--tag", help="Tags for this credential (repeatable)."),
) -> None:
    """Add a new credential to the vault.

    Examples:
        agentjam vault add github --value ghp_xxx --tag git
        agentjam vault add openai --tag production   (prompts for value)
    """
    from agentjam.vault.store import Credential

    store = _get_vault()
    if store.lock_state != LockState.UNLOCKED:
        typer.echo("Vault is locked. Use 'vault unlock' first.")
        raise typer.Exit(1)

    # If no value given on CLI, prompt securely.
    if not value:
        value = typer.prompt("Credential value", hide_input=True)
        confirm = typer.prompt("Confirm value", hide_input=True)
        if value != confirm:
            typer.echo("Values do not match.")
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

# Global task store reference.
_task_store: TaskStore | None = None


def _get_task_store() -> TaskStore:
    global _task_store
    if _task_store is None:
        _task_store = TaskStore(tasks_dir())
    return _task_store


@task_app.command(name="list")
def list_tasks(
    status: str = typer.Option("", "--status", help="Filter by status."),
    project: str = typer.Option("", "--project", help="Filter by project."),
    limit: int = typer.Option(0, "--limit", help="Max tasks to show."),
) -> None:
    """List tasks."""
    store = _get_task_store()
    tasks = store.list(status=status, project=project, limit=limit)
    if not tasks:
        typer.echo("No tasks found.")
        return
    for t in tasks:
        status_icon = _status_icon(t.status)
        typer.echo(f"  {status_icon} {t.id:28s}  {t.priority.value:7s}  {t.title[:60]}")


@task_app.command()
def create(
    title: str = typer.Argument(..., help="Task title."),
    description: str = typer.Option("", "--description", help="Longer description."),
    priority: str = typer.Option("medium", "--priority", help="Priority (low, medium, high, urgent)."),
    project: str = typer.Option("", "--project", help="Project ID."),
    tag: list[str] = typer.Option([], "--tag", help="Tags (repeatable)."),
    criteria: list[str] = typer.Option([], "--criteria", help="Acceptance criteria (repeatable)."),
) -> None:
    """Create a new task."""
    from agentjam.task.models import new_task_id

    store = _get_task_store()
    task = Task(
        id=new_task_id(project),
        title=title,
        description=description,
        priority=Priority(priority),
        project=project,
        tags=list(tag),
        acceptance_criteria=list(criteria),
    )
    store.create(task)
    typer.echo(f"Task created: {task.id}")
    typer.echo(f"  {task.title}")


@task_app.command()
def show(task_id: str = typer.Argument(..., help="Task ID.")) -> None:
    """Show full task details."""
    store = _get_task_store()
    task = store.get(task_id)
    if task is None:
        typer.echo(f"Task {task_id!r} not found.")
        raise typer.Exit(1)

    typer.echo(f"Task: {task.id}")
    typer.echo(f"  Title:       {task.title}")
    typer.echo(f"  Status:      {task.status.value}")
    typer.echo(f"  Priority:    {task.priority.value}")
    typer.echo(f"  Project:     {task.project or '—'}")
    typer.echo(f"  Assigned to: {task.assigned_to or '—'}")
    if task.tags:
        typer.echo(f"  Tags:        {', '.join(task.tags)}")
    if task.description:
        typer.echo(f"  Description: {task.description}")
    if task.acceptance_criteria:
        typer.echo("  Acceptance criteria:")
        for c in task.acceptance_criteria:
            typer.echo(f"    - {c}")
    if task.steps:
        typer.echo("  Steps:")
        for s in task.steps:
            icon = _status_icon(s.status)
            typer.echo(f"    {icon} {s.title}")
    if task.progress:
        typer.echo(f"  Progress ({len(task.progress)} entries):")
        for p in task.progress[-5:]:
            ts = _format_ts(p.timestamp)
            typer.echo(f"    [{ts}] {p.status.value}: {p.entry[:80]}")


@task_app.command()
def update(
    task_id: str = typer.Argument(..., help="Task ID."),
    status: str = typer.Option("", "--status", help="New status."),
    title: str = typer.Option("", "--title", help="New title."),
    assign: str = typer.Option("", "--assign", help="Agent ID to assign (empty to unassign)."),
) -> None:
    """Update a task."""
    store = _get_task_store()
    task = store.get(task_id)
    if task is None:
        typer.echo(f"Task {task_id!r} not found.")
        raise typer.Exit(1)

    if status:
        task = store.set_status(task_id, TaskStatus(status))
    if title:
        task.title = title
        task = store.update(task)
    if assign is not None:
        task = store.assign(task_id, assign)

    typer.echo(f"Task {task.id} updated.")


@task_app.command()
def delete(task_id: str = typer.Argument(..., help="Task ID to delete.")) -> None:
    """Delete a task."""
    store = _get_task_store()
    store.delete(task_id)
    typer.echo(f"Task {task_id} deleted.")


def _status_icon(status: TaskStatus) -> str:
    icons = {
        TaskStatus.DRAFT: "○",
        TaskStatus.OPEN: "◌",
        TaskStatus.PLANNED: "◔",
        TaskStatus.IN_PROGRESS: "●",
        TaskStatus.BLOCKED: "⚠",
        TaskStatus.REVIEW: "◉",
        TaskStatus.DONE: "✓",
        TaskStatus.ABANDONED: "✗",
    }
    return icons.get(status, "?")


# ── settings commands ────────────────────────────────────────────────────────


@settings_app.command()
def show() -> None:
    """Show current settings."""
    typer.echo("Not yet implemented.")


if __name__ == "__main__":
    app()
