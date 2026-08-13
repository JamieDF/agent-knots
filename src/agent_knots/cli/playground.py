"""`agent-knots playground` subcommands.

Maintainer tooling, not something a user of the playground ever runs:
these produce the demo repo's task manifest. Consuming it is the web
cockpit's job (Settings → Create playground).
"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_knots.config import projects_dir, tasks_dir
from agent_knots.playground import ManifestError, read_manifest, write_manifest
from agent_knots.project.store import ProjectStore
from agent_knots.task.store import TaskStore

playground_app = typer.Typer(
    help="Build the demo playground's task manifest (maintainer tooling).",
    no_args_is_help=True,
)


@playground_app.command(name="export")
def export_manifest(
    project: str = typer.Option(..., "--project", help="Workspace id whose tasks to export."),
    repo: str = typer.Option(
        "", "--repo",
        help="Repo to write .agent-knots/playground.yaml into. "
             "Defaults to the workspace's own folder.",
    ),
) -> None:
    """Write a workspace's tasks into its repo as a playground manifest."""
    store = ProjectStore(projects_dir())
    ws = store.get(project)
    if ws is None:
        typer.echo(f"Error: workspace {project!r} not found")
        raise typer.Exit(1)

    target = Path(repo).expanduser() if repo else Path(ws.repository)
    if not target or not target.is_dir():
        typer.echo(f"Error: {target} is not a directory")
        raise typer.Exit(1)

    tasks = TaskStore(tasks_dir()).list(project=project)
    if not tasks:
        typer.echo(f"Error: workspace {project!r} has no tasks to export")
        raise typer.Exit(1)

    path = write_manifest(target, tasks)
    by_status: dict[str, int] = {}
    for t in tasks:
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
    spread = ", ".join(f"{n} {s}" for s, n in sorted(by_status.items()))
    typer.echo(f"Wrote {len(tasks)} tasks to {path}")
    typer.echo(f"  {spread}")
    typer.echo("Commit it so the tasks travel with the repo.")


@playground_app.command(name="show")
def show_manifest(
    repo: str = typer.Argument(..., help="Repo containing .agent-knots/playground.yaml."),
) -> None:
    """Print what a repo's manifest would import, without importing it."""
    try:
        tasks = read_manifest(Path(repo).expanduser(), project_id="(preview)")
    except ManifestError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)

    typer.echo(f"{len(tasks)} task(s):")
    for t in tasks:
        criteria = f"  [{len(t.acceptance_criteria)} criteria]" if t.acceptance_criteria else ""
        typer.echo(f"  {t.status.value:12s} {t.title}{criteria}")
