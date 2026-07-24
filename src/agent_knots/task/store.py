"""YAML file-backed task store.

Each task is a YAML file in ~/.agent-knots/tasks/<id>.yaml.
Atomic writes via write-to-tmp-then-rename.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_knots.task.models import (
    Blocker,
    Priority,
    ProgressEntry,
    ReviewGate,
    Step,
    Task,
    TaskStatus,
)
from agent_knots.yamlfile import atomic_write_yaml, safe_read_yaml


def _step_to_dict(step: Step) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": step.id,
        "title": step.title,
        "status": step.status.value,
    }
    if step.notes:
        d["notes"] = step.notes
    if step.sub_steps:
        d["sub_steps"] = [_step_to_dict(s) for s in step.sub_steps]
    return d


def _step_from_dict(d: dict[str, Any]) -> Step:
    return Step(
        id=d["id"],
        title=d["title"],
        status=TaskStatus(d.get("status", "draft")),
        notes=d.get("notes", ""),
        sub_steps=[_step_from_dict(s) for s in d.get("sub_steps", [])],
    )


def _blocker_to_dict(b: Blocker) -> dict[str, Any]:
    d: dict[str, Any] = {
        "description": b.description,
        "awaiting": b.awaiting,
    }
    if b.question:
        d["question"] = b.question
    if b.options:
        d["options"] = b.options
    return d


def _blocker_from_dict(d: dict[str, Any]) -> Blocker:
    return Blocker(
        description=d["description"],
        awaiting=d.get("awaiting", "user"),
        question=d.get("question", ""),
        options=d.get("options", []),
    )


def _progress_to_dict(p: ProgressEntry) -> dict[str, Any]:
    d: dict[str, Any] = {
        "timestamp": p.timestamp,
        "status": p.status.value,
        "entry": p.entry,
        "caller": p.caller,
    }
    if p.actions_taken:
        d["actions_taken"] = p.actions_taken
    if p.blocker:
        d["blocker"] = _blocker_to_dict(p.blocker)
    if p.resolution:
        d["resolution"] = p.resolution
    if p.next_step:
        d["next_step"] = p.next_step
    return d


def _progress_from_dict(d: dict[str, Any]) -> ProgressEntry:
    return ProgressEntry(
        timestamp=d.get("timestamp", time.time()),
        status=TaskStatus(d.get("status", "in_progress")),
        entry=d.get("entry", ""),
        actions_taken=d.get("actions_taken", []),
        blocker=_blocker_from_dict(d["blocker"]) if "blocker" in d else None,
        resolution=d.get("resolution", ""),
        next_step=d.get("next_step", ""),
        caller=d.get("caller", "user"),
    )


def _task_to_dict(task: Task) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
        "created_at": task.created_at,
        "created_by": task.created_by,
        "updated_at": task.updated_at,
    }
    if task.description:
        d["description"] = task.description
    if task.tags:
        d["tags"] = task.tags
    if task.project:
        d["project"] = task.project
    if task.review_gate != ReviewGate.MANUAL:
        d["review_gate"] = task.review_gate.value
    if task.acceptance_criteria:
        d["acceptance_criteria"] = task.acceptance_criteria
    if task.criteria_met:
        d["criteria_met"] = task.criteria_met
    if task.out_of_scope:
        d["out_of_scope"] = task.out_of_scope
    if task.steps:
        d["steps"] = [_step_to_dict(s) for s in task.steps]
    if task.dependencies:
        d["dependencies"] = task.dependencies
    if task.required_credentials:
        d["required_credentials"] = task.required_credentials
    if task.assigned_to:
        d["assigned_to"] = task.assigned_to
    if task.progress:
        d["progress"] = [_progress_to_dict(p) for p in task.progress]
    return d


def _task_from_dict(d: dict[str, Any]) -> Task:
    return Task(
        id=d["id"],
        title=d["title"],
        description=d.get("description", ""),
        status=TaskStatus(d.get("status", "open")),
        priority=Priority(d.get("priority", "medium")),
        tags=d.get("tags", []),
        project=d.get("project", ""),
        review_gate=ReviewGate(d.get("review_gate", "manual")),
        acceptance_criteria=d.get("acceptance_criteria", []),
        criteria_met=d.get("criteria_met", []),
        out_of_scope=d.get("out_of_scope", []),
        steps=[_step_from_dict(s) for s in d.get("steps", [])],
        dependencies=d.get("dependencies", []),
        required_credentials=d.get("required_credentials", []),
        assigned_to=d.get("assigned_to", ""),
        created_at=d.get("created_at", time.time()),
        created_by=d.get("created_by", "user"),
        updated_at=d.get("updated_at", time.time()),
        progress=[_progress_from_dict(p) for p in d.get("progress", [])],
    )


# ── store ────────────────────────────────────────────────────────────────────


class TaskStore:
    """YAML file-backed CRUD store for tasks."""

    def __init__(self, tasks_dir: Path) -> None:
        self._dir = Path(tasks_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.yaml"

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create(self, task: Task) -> Task:
        """Persist a new task. Raises ValueError if ID exists."""
        path = self._path(task.id)
        if path.exists():
            raise ValueError(f"task {task.id!r} already exists")
        task.created_at = time.time()
        task.updated_at = task.created_at
        self._save(task)
        return task

    def get(self, task_id: str) -> Task | None:
        """Return a task by ID, or None."""
        path = self._path(task_id)
        if not path.exists():
            return None
        return self._load(path)

    def list(self, *, status: str = "", project: str = "",
             assigned_to: str = "", tags: list[str] | None = None,
             limit: int = 0) -> list[Task]:
        """List tasks with optional filters, ordered by updated_at descending."""
        tasks = []
        for path in sorted(self._dir.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
            task = self._load(path)
            if task is None:
                continue
            if status and task.status.value != status:
                continue
            if project and task.project != project:
                continue
            if assigned_to and task.assigned_to != assigned_to:
                continue
            if tags and not all(t in task.tags for t in tags):
                continue
            tasks.append(task)
            if limit and len(tasks) >= limit:
                break
        return tasks

    def update(self, task: Task) -> Task:
        """Replace a task. Raises ValueError if not found."""
        if not self._path(task.id).exists():
            raise ValueError(f"task {task.id!r} not found")
        task.updated_at = time.time()
        self._save(task)
        return task

    def delete(self, task_id: str) -> None:
        """Delete a task. Raises ValueError if not found."""
        path = self._path(task_id)
        if not path.exists():
            raise ValueError(f"task {task_id!r} not found")
        path.unlink()

    # ── operations ───────────────────────────────────────────────────────

    def log_progress(self, task_id: str, entry: ProgressEntry) -> Task:
        """Append a progress entry.

        A progress entry can carry a status change (entry.status), which
        goes through the same validation as set_status() — most notably
        the DONE acceptance-criteria/review-gate gates — since this is
        otherwise a second path to change status that would bypass them.
        Only ever called from the agent tool (task/tools.py), never from a
        human-facing route, so this intentionally relies on
        _validate_transition's "agent" default rather than taking its own
        actor parameter.
        """
        task = self._must_get(task_id)
        if entry.status and entry.status != task.status:
            self._validate_transition(task, entry.status)
        task.log_progress(entry)
        self._save(task)
        return task

    def assign(self, task_id: str, agent_id: str) -> Task:
        """Assign a task to an agent. Pass empty string to unassign."""
        task = self._must_get(task_id)
        task.assign(agent_id)
        self._save(task)
        return task

    def set_status(self, task_id: str, status: TaskStatus, actor: str = "agent") -> Task:
        """Transition task to a new status.

        actor distinguishes a human (the web PATCH route) from an agent
        (task tools) — see _validate_transition for why this matters for
        the done transition. Defaults to the more restrictive "agent" so
        any new call site has to opt in to "human" deliberately rather
        than silently getting agent self-review for free.
        """
        task = self._must_get(task_id)
        self._validate_transition(task, status, actor)
        task.status = status
        task.updated_at = time.time()
        self._save(task)
        return task

    def _validate_transition(self, task: Task, new_status: TaskStatus, actor: str = "agent") -> None:
        """Raise ValueError if transitioning to new_status isn't allowed."""
        if new_status == TaskStatus.DONE:
            if not task.all_criteria_met():
                unmet = task.unmet_criteria()
                raise ValueError(
                    f"cannot mark task {task.id!r} done — unmet acceptance criteria: {unmet}"
                )
            # The workflow requires a review step before done, unless the
            # task's own review_gate opts out of it — a task with zero
            # acceptance criteria would otherwise sail straight from
            # in_progress to done with no check at all.
            if task.review_gate != ReviewGate.NONE:
                if task.status != TaskStatus.REVIEW:
                    raise ValueError(
                        f"cannot mark task {task.id!r} done directly from {task.status.value!r} — "
                        f"move it to 'review' first (review_gate={task.review_gate.value!r}; "
                        f"set review_gate to 'none' to skip review for this task)"
                    )
                # Being in 'review' status isn't itself proof anything was
                # reviewed — an agent can call update_task_status('review')
                # immediately followed by update_task_status('done') in the
                # same turn, satisfying this check without anyone but
                # itself ever looking at the work. review_gate != "none"
                # means a human has to be the one to actually close it out;
                # the same agent that did the work can move a task INTO
                # review, but never grant itself the done transition.
                if actor != "human":
                    raise ValueError(
                        f"cannot mark task {task.id!r} done — review_gate="
                        f"{task.review_gate.value!r} requires a human to complete "
                        f"the review, not the same agent that did the work "
                        f"(set review_gate to 'none' if this task doesn't need review)"
                    )
        if new_status == TaskStatus.IN_PROGRESS:
            unmet = self.unmet_dependencies(task)
            if unmet:
                blockers = ", ".join(f"{t.id} ({t.title!r})" for t in unmet)
                raise ValueError(
                    f"cannot start task {task.id!r} — blocked by unfinished "
                    f"dependencies: {blockers}"
                )

    def unmet_dependencies(self, task: Task) -> list[Task]:
        """Return task.dependencies entries that aren't done yet.

        A dependency id that no longer resolves to a real task (deleted)
        is treated as not blocking, rather than locking the task forever
        on a dangling reference.
        """
        unmet = []
        for dep_id in task.dependencies:
            dep = self.get(dep_id)
            if dep is not None and dep.status != TaskStatus.DONE:
                unmet.append(dep)
        return unmet

    def mark_criterion_met(self, task_id: str, criterion: str) -> Task:
        """Mark a single acceptance criterion as satisfied."""
        task = self._must_get(task_id)
        if criterion not in task.acceptance_criteria:
            raise ValueError(f"{criterion!r} is not an acceptance criterion of {task_id!r}")
        if criterion not in task.criteria_met:
            task.criteria_met.append(criterion)
            task.updated_at = time.time()
            self._save(task)
        return task

    def unmark_criterion_met(self, task_id: str, criterion: str) -> Task:
        """Undo a previous mark_criterion_met — e.g. if it turns out unmet."""
        task = self._must_get(task_id)
        if criterion in task.criteria_met:
            task.criteria_met.remove(criterion)
            task.updated_at = time.time()
            self._save(task)
        return task

    def add_step(self, task_id: str, step: Step) -> Task:
        """Add a step to the task plan."""
        task = self._must_get(task_id)
        task.steps.append(step)
        task.updated_at = time.time()
        self._save(task)
        return task

    # ── internal ─────────────────────────────────────────────────────────

    def _must_get(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} not found")
        return task

    def _save(self, task: Task) -> None:
        atomic_write_yaml(self._path(task.id), _task_to_dict(task))

    def _load(self, path: Path) -> Task | None:
        data = safe_read_yaml(path)
        if not isinstance(data, dict) or "id" not in data:
            return None
        try:
            return _task_from_dict(data)
        except KeyError:
            return None
