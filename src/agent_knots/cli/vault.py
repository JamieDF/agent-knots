"""`agent-knots vault` subcommands, including `vault template`."""

from __future__ import annotations

import typer

from agent_knots.cli._format import format_ts
from agent_knots.config import vault_dir
from agent_knots.vault.store import LockState, VaultStore

vault_app = typer.Typer(help="Manage the encrypted credential vault.", no_args_is_help=True)

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
        agent-knots vault add github --value ghp_xxx --tag git
        agent-knots vault add openai --tag production   (prompts for value)
    """
    from agent_knots.vault.store import Credential

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
    from agent_knots.vault.store import AuditOptions

    store = _get_vault()
    entries = store.audit_log(AuditOptions(credential=cred_id, limit=limit))
    if not entries:
        typer.echo("No audit entries.")
        return
    for e in entries:
        status = "✓" if e.success else "✗"
        ts = format_ts(e.timestamp)
        typer.echo(f"  {ts}  {status}  {e.credential:25s}  {e.caller:15s}  {e.template}")


# ── vault template commands ──────────────────────────────────────────────────

vault_template_app = typer.Typer(
    help="Manage credential injection templates.", no_args_is_help=True
)
vault_app.add_typer(vault_template_app, name="template")


@vault_template_app.command(name="add")
def template_add(
    cred_id: str = typer.Argument(..., help="Credential ID (e.g. 'github/work')."),
    name: str = typer.Option(..., "--name", help="Template name (e.g. 'gh_cli_env')."),
    description: str = typer.Option("", "--description", help="Human-readable note."),
    env: str = typer.Option(
        "", "--env", help='JSON object of env vars to inject, e.g. \'{"GH_TOKEN": "$value"}\'.'
    ),
    file_path: str = typer.Option(
        "", "--file", help="Write the value to this path instead of an env var."
    ),
    file_permissions: str = typer.Option(
        "600", "--file-permissions", help="Octal permissions for --file (default 600)."
    ),
    stdin: bool = typer.Option(False, "--stdin", help="Pipe the value to the command's stdin."),
    wrapper: str = typer.Option(
        "", "--wrapper", help="Command wrapper template using {original} and $value."
    ),
) -> None:
    """Add or replace an injection template on a credential.

    Examples:
        agent-knots vault template add github/work --name gh_cli_env --env '{"GH_TOKEN": "$value"}'
        agent-knots vault template add github/work --name curl_bearer --wrapper "curl -H 'Authorization: token $value' {original}"
    """
    import json

    from agent_knots.vault.store import InjectionTemplate

    store = _get_vault()
    if store.lock_state != LockState.UNLOCKED:
        typer.echo("Vault is locked. Use 'vault unlock' first.")
        raise typer.Exit(1)

    try:
        env_dict = json.loads(env) if env else {}
        if not isinstance(env_dict, dict):
            raise ValueError("--env must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        typer.echo(f"Error: invalid --env: {e}")
        raise typer.Exit(1)

    try:
        store.set_template(cred_id, InjectionTemplate(
            name=name,
            description=description,
            env=env_dict,
            file_path=file_path or None,
            file_permissions=int(file_permissions, 8),
            stdin=stdin,
            command_wrapper=wrapper or None,
        ))
        typer.echo(f"Template '{name}' added to '{cred_id}'.")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)


@vault_template_app.command(name="list")
def template_list(cred_id: str = typer.Argument(..., help="Credential ID.")) -> None:
    """List templates on a credential."""
    store = _get_vault()
    templates = store.list_templates(cred_id)
    if not templates:
        typer.echo("No templates.")
        return
    for t in templates:
        kind = "env" if t.env else "file" if t.file_path else "stdin" if t.stdin else "wrapper"
        typer.echo(f"  {t.name:20s}  {kind:8s}  {t.description}")


@vault_template_app.command(name="show")
def template_show(
    cred_id: str = typer.Argument(..., help="Credential ID."),
    name: str = typer.Argument(..., help="Template name."),
) -> None:
    """Show a template's injection config."""
    store = _get_vault()
    t = store.get_template(cred_id, name)
    if t is None:
        typer.echo(f"Template {name!r} not found on {cred_id!r}.")
        raise typer.Exit(1)
    typer.echo(f"Name:        {t.name}")
    typer.echo(f"Description: {t.description or '—'}")
    if t.env:
        typer.echo(f"Env:         {t.env}")
    if t.file_path:
        typer.echo(f"File:        {t.file_path} (mode {oct(t.file_permissions)})")
    if t.stdin:
        typer.echo("Stdin:       yes")
    if t.command_wrapper:
        typer.echo(f"Wrapper:     {t.command_wrapper}")


@vault_template_app.command(name="remove")
def template_remove(
    cred_id: str = typer.Argument(..., help="Credential ID."),
    name: str = typer.Argument(..., help="Template name to remove."),
) -> None:
    """Remove a template from a credential."""
    store = _get_vault()
    try:
        store.remove_template(cred_id, name)
        typer.echo(f"Template '{name}' removed from '{cred_id}'.")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)
