"""`agent-knots project` subcommands."""

from __future__ import annotations

import typer

from agent_knots.project.models import Project
from agent_knots.storage import project_store

project_app = typer.Typer(help="Manage projects (multi-repo workspaces).", no_args_is_help=True)


def _get_project_store():
    return project_store()


@project_app.command(name="create")
def create_project(
    project_id: str = typer.Argument(..., help="Project ID (e.g. 'my-app')."),
    name: str = typer.Option(..., "--name", help="Human-readable project name."),
    description: str = typer.Option("", "--description", help="Longer description."),
    repository: str = typer.Option("", "--repository", "--repo", help="Repo URL or path."),
    managed: bool = typer.Option(
        False, "--managed",
        help="Clone the repo into a folder agent-knots owns, instead of using --repository "
             "in place. Agents then work on the copy and your own checkout is left alone.",
    ),
    init_git: bool = typer.Option(
        False, "--init-git", help="With --managed and no --repository: git init the new folder.",
    ),
    default_branch: str = typer.Option("main", "--branch", help="Default branch."),
    runtime: str = typer.Option("", "--runtime", help="Runtime override (inprocess, or empty for the global default)."),
    tag: list[str] = typer.Option([], "--tag", help="Tags (repeatable)."),
) -> None:
    """Create a new project."""
    store = _get_project_store()
    if store.get(project_id) is not None:
        typer.echo(f"Error: Project {project_id!r} already exists")
        raise typer.Exit(1)

    source = repository.strip()
    if managed:
        # Provision before the record exists, so a failed clone leaves
        # neither a directory nor a project pointing at one.
        from agent_knots.config import workspaces_root
        from agent_knots.gitutil import (
            clone_into,
            init_repo,
            repo_name_from_source,
            unique_clone_dir,
        )

        dest = unique_clone_dir(workspaces_root(), repo_name_from_source(source, project_id))
        if source:
            typer.echo(f"Cloning {source} into {dest} ...")
            result = clone_into(source, dest)
            if not result.ok:
                typer.echo(f"Error: clone failed: {result.failed_reason}")
                raise typer.Exit(1)
            repository = result.path
        else:
            dest.mkdir(parents=True, exist_ok=True)
            if init_git:
                init_repo(dest)
            repository = str(dest)
        typer.echo(f"Workspace folder: {repository}")

    project = Project(
        id=project_id,
        name=name,
        description=description,
        repository=repository,
        source=source if managed else "",
        managed=managed,
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
    if project.managed:
        origin = project.source or "nothing — created empty"
        typer.echo(f"  Managed:        yes (cloned from {origin})")
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
