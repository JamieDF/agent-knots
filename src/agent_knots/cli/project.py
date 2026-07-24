"""`agent-knots project` subcommands."""

from __future__ import annotations

import typer

from agent_knots.config import projects_dir
from agent_knots.project.models import Project
from agent_knots.project.store import ProjectStore

project_app = typer.Typer(help="Manage projects (multi-repo workspaces).", no_args_is_help=True)

# Global project store reference.
_project_store: ProjectStore | None = None


def _get_project_store() -> ProjectStore:
    global _project_store
    if _project_store is None:
        _project_store = ProjectStore(projects_dir())
    return _project_store


@project_app.command(name="create")
def create_project(
    project_id: str = typer.Argument(..., help="Project ID (e.g. 'my-app')."),
    name: str = typer.Option(..., "--name", help="Human-readable project name."),
    description: str = typer.Option("", "--description", help="Longer description."),
    repository: str = typer.Option("", "--repository", "--repo", help="Repo URL or path."),
    default_branch: str = typer.Option("main", "--branch", help="Default branch."),
    runtime: str = typer.Option("", "--runtime", help="Runtime override (inprocess, or empty for the global default)."),
    tag: list[str] = typer.Option([], "--tag", help="Tags (repeatable)."),
) -> None:
    """Create a new project."""
    store = _get_project_store()
    project = Project(
        id=project_id,
        name=name,
        description=description,
        repository=repository,
        default_branch=default_branch,
        runtime=runtime,
        tags=list(tag),
    )
    try:
        store.create(project)
        typer.echo(f"Project created: {project.id}")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)


@project_app.command(name="list")
def list_projects() -> None:
    """List all projects."""
    store = _get_project_store()
    projects = store.list()
    if not projects:
        typer.echo("No projects found.")
        return
    for p in projects:
        tags = ", ".join(p.tags) if p.tags else ""
        typer.echo(f"  {p.id:20s}  {p.name:30s}  {tags}")


@project_app.command(name="show")
def show_project(project_id: str = typer.Argument(..., help="Project ID.")) -> None:
    """Show full project details."""
    store = _get_project_store()
    project = store.get(project_id)
    if project is None:
        typer.echo(f"Project {project_id!r} not found.")
        raise typer.Exit(1)

    typer.echo(f"Project: {project.id}")
    typer.echo(f"  Name:           {project.name}")
    typer.echo(f"  Description:    {project.description or '—'}")
    typer.echo(f"  Repository:     {project.repository or '—'}")
    typer.echo(f"  Default branch: {project.default_branch}")
    typer.echo(f"  Runtime:        {project.runtime or '(global default)'}")
    if project.tags:
        typer.echo(f"  Tags:           {', '.join(project.tags)}")


@project_app.command(name="update")
def update_project(
    project_id: str = typer.Argument(..., help="Project ID."),
    name: str = typer.Option("", "--name", help="New name."),
    description: str = typer.Option("", "--description", help="New description."),
    repository: str = typer.Option("", "--repository", "--repo", help="New repository URL or path."),
    default_branch: str = typer.Option("", "--branch", help="New default branch."),
    runtime: str = typer.Option("", "--runtime", help="New runtime override."),
) -> None:
    """Update a project."""
    store = _get_project_store()
    project = store.get(project_id)
    if project is None:
        typer.echo(f"Project {project_id!r} not found.")
        raise typer.Exit(1)

    if name:
        project.name = name
    if description:
        project.description = description
    if repository:
        project.repository = repository
    if default_branch:
        project.default_branch = default_branch
    if runtime:
        project.runtime = runtime

    store.update(project)
    typer.echo(f"Project {project.id} updated.")


@project_app.command(name="delete")
def delete_project(project_id: str = typer.Argument(..., help="Project ID to delete.")) -> None:
    """Delete a project."""
    store = _get_project_store()
    try:
        store.delete(project_id)
        typer.echo(f"Project {project_id} deleted.")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)
