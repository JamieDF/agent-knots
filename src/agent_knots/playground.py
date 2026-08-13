"""Playground manifest — a demo project's tasks, carried in its repo.

The playground is a real, half-finished project someone can stand up in
one click to see what agent-knots actually does. It's built *with*
agent-knots, so the tasks that ship with it are the genuine ones that
built it: real progress logs, real branches, some done, one waiting on
review, some never started.

Those tasks normally live in ~/.agent-knots/tasks/ — outside any repo,
keyed to a workspace by a bare `project` string. To travel with the
code they get written into the repo as `.agent-knots/playground.yaml`,
which `agent-knots playground export` produces and workspace creation
reads back.

Deliberately demo-only, not a general "task state travels with the
repo" feature. Tasks are moving to a real database (see roadmap), which
would rewrite this format wholesale; building it as a supported
capability now would mean maintaining a migration path for something
with exactly one consumer. Keeping it playground-shaped means it can be
thrown away and rewritten without ceremony.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_knots.task.models import Task
from agent_knots.task.store import task_from_dict, task_to_dict
from agent_knots.yamlfile import atomic_write_yaml, safe_read_yaml

# Bumped if the shape changes incompatibly. Readers refuse anything
# newer than they understand rather than silently half-importing.
MANIFEST_VERSION = 1

# Relative to the repo root. Dotted so it reads as tooling rather than
# part of the demo app itself.
MANIFEST_PATH = Path(".agent-knots") / "playground.yaml"


class ManifestError(Exception):
    """A manifest that can't be read or trusted."""


def manifest_path(repo: Path) -> Path:
    return Path(repo) / MANIFEST_PATH


def has_manifest(repo: Path) -> bool:
    return manifest_path(repo).is_file()


def build_manifest(tasks: list[Task]) -> dict[str, Any]:
    """Serialise tasks for shipping inside a repo.

    Two departures from what the store writes:

    `assigned_to` is dropped — it holds a session id from the machine
    that built the demo, which means nothing anywhere else and would
    make an imported task look like it had a live agent on it.

    `progress` is deliberately kept. It's the real tool calls and notes
    from the agents that did the work, and it's the single most
    convincing part of the demo: a task whose log shows it actually
    happened reads very differently from one that just claims a status.
    """
    entries = []
    for task in sorted(tasks, key=lambda t: t.created_at):
        d = task_to_dict(task)
        d.pop("assigned_to", None)
        # Rewritten to the importing workspace, so carrying the
        # exporter's id would just be noise to resolve later.
        d.pop("project", None)
        entries.append(d)
    return {"version": MANIFEST_VERSION, "tasks": entries}


def write_manifest(repo: Path, tasks: list[Task]) -> Path:
    """Write the manifest into `repo`, creating .agent-knots/ if needed."""
    path = manifest_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(path, build_manifest(tasks))
    return path


def read_manifest(repo: Path, project_id: str) -> list[Task]:
    """Load a repo's manifest as Tasks bound to `project_id`.

    Task ids are preserved exactly, which is load-bearing rather than
    tidiness: gitutil.session_branch_name derives a branch from
    sha1(task_id)[:6] plus the title slug, so the demo's in-review task
    only lines up with the branch pushed alongside it if both its id and
    title survive the round trip unchanged. Preserving ids also keeps
    `dependencies` pointing at the right tasks with no remapping.

    Raises ManifestError rather than returning a partial import — a
    half-seeded board is worse than none.
    """
    path = manifest_path(repo)
    if not path.is_file():
        raise ManifestError(f"no playground manifest at {path}")

    data = safe_read_yaml(path)
    if not isinstance(data, dict):
        raise ManifestError(f"{path} is not a mapping")

    version = data.get("version")
    if not isinstance(version, int) or version > MANIFEST_VERSION:
        raise ManifestError(
            f"manifest version {version!r} is newer than this agent-knots "
            f"understands (max {MANIFEST_VERSION}) — upgrade to import it",
        )

    raw = data.get("tasks")
    if not isinstance(raw, list):
        raise ManifestError(f"{path} has no tasks list")

    tasks = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ManifestError(f"task {i} is not a mapping")
        try:
            task = task_from_dict({**entry, "project": project_id})
        except (KeyError, ValueError) as e:
            raise ManifestError(f"task {i} is unreadable: {e}") from e
        # Belt and braces: a manifest that somehow carries an
        # assigned_to would otherwise seed a task pointing at a session
        # that has never existed on this machine.
        task.assigned_to = ""
        tasks.append(task)
    return tasks
