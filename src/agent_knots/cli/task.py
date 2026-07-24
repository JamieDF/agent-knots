"""`agent-knots task` subcommands."""

from __future__ import annotations

import typer

from agent_knots.cli._format import format_ts
from agent_knots.config import tasks_dir
from agent_knots.task.models import Priority, Task, TaskStatus
from agent_knots.task.store import TaskStore

task_app = typer.Typer(help="Manage structured tasks.", no_args_is_help=True)

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
    from agent_knots.task.models import new_task_id

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
            ts = format_ts(p.timestamp)
            typer.echo(f"    [{ts}] {p.status.value}: {p.entry[:80]}")


@task_app.command()
def update(
    task_id: str = typer.Argument(..., help="Task ID."),
    status: str = typer.Option("", "--status", help="New status."),
    title: str = typer.Option("", "--title", help="New title."),
    assign: str | None = typer.Option(None, "--assign", help="Agent ID to assign. Pass an empty string to unassign."),
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
