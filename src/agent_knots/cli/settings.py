"""`agent-knots settings` subcommands."""

from __future__ import annotations

import typer

settings_app = typer.Typer(help="View and change global settings.", no_args_is_help=True)


@settings_app.command()
def show() -> None:
    """Show current settings."""
    typer.echo("Not yet implemented.")
