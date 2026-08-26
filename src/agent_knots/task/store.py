"""SQLite-backed task store.

Tasks are stored in ~/.agent-knots/state.db with indexed columns for
common queries and a JSON blob for the full record.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from agent_knots.storage.db import get_connection
from agent_knots.task.models import (
    Blocker,
    Priority,
    ProgressEntry,
    ReviewGate,
    Step,
    Task,
    TaskStatus,
)


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
    if p.role:
        d["role"] = p.role
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
        role=d.get("role", ""),
    )


def task_to_dict(task: Task) -> dict[str, Any]:
    """Task -> plain dict for JSON storage.

    Public because the playground exporter serialises tasks into a
    repo-committed manifest and must produce identical shapes.
    """
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
    if task.merged_into:
        d["merged_into"] = task.merged_into
    if task.pull_request_url:
        d["pull_request_url"] = task.pull_request_url
    if task.progress:
        d["progress"] = [_progress_to_dict(p) for p in task.progress]
    return d


def task_from_dict(d: dict[str, Any]) -> Task:
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
        merged_into=d.get("merged_into", ""),
        pull_request_url=d.get("pull_request_url", ""),
        created_at=d.get("created_at", time.time()),
        created_by=d.get("created_by", "user"),
        updated_at=d.get("updated_at", time.time()),
        progress=[_progress_from_dict(p) for p in d.get("progress", [])],
    )


class TaskStore:
    """SQLite-backed CRUD store for tasks."""

    _write_lock = threading.RLock()

    def __init__(self, db_path: Path) -> None:
        self._conn = get_connection(db_path)

    @contextlib.contextmanager
    def _task_lock(self, task_id: str):
        """Exclusive lock for read-modify-write on one task."""
        del task_id
        with self._write_lock:
            yield

    def create(self, task: Task) -> Task:
        """Persist a new task. Raises ValueError if ID exists."""
        if self.get(task.id) is not None:
            raise ValueError(f"task {task.id!r} already exists")
        task.created_at = time.time()
        task.updated_at = task.created_at
        self._save(task)
        return task

    def get(self, task_id: str) -> Task | None:
        """Return a task by ID, or None."""
        row = self._conn.execute(
            "SELECT data FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return self._load_json(row[0])

    def list(self, *, status: str = "", project: str = "",
             assigned_to: str = "", tags: list[str] | None = None,
             limit: int = 0) -> list[Task]:
        """List tasks with optional filters, ordered by updated_at descending."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if project:
            clauses.append("project = ?")
            params.append(project)
        if assigned_to:
            clauses.append("assigned_to = ?")
            params.append(assigned_to)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT data FROM tasks{where} ORDER BY updated_at DESC"
        if limit and not tags:
            sql += " LIMIT ?"
            params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        tasks: list[Task] = []
        for row in rows:
            task = self._load_json(row[0])
            if task is None:
                continue
            if tags and not all(t in task.tags for t in tags):
                continue
            tasks.append(task)
            if limit and len(tasks) >= limit:
                break
        return tasks

    def update(self, task: Task) -> Task:
        """Replace a task. Raises ValueError if not found."""
        if self.get(task.id) is None:
            raise ValueError(f"task {task.id!r} not found")
        task.updated_at = time.time()
        self._save(task)
        return task

    def delete(self, task_id: str) -> None:
        """Delete a task. Raises ValueError if not found."""
        if self.get(task_id) is None:
            raise ValueError(f"task {task_id!r} not found")
        with self._write_lock:
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            self._conn.commit()

    def log_progress(self, task_id: str, entry: ProgressEntry) -> Task:
        """Append a progress entry."""
        with self._task_lock(task_id):
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
        """Transition task to a new status."""
        task = self._must_get(task_id)
        self._validate_transition(task, status, actor)
        task.status = status
        task.updated_at = time.time()
        self._save(task)
        return task

    def _validate_transition(
        self, task: Task, new_status: TaskStatus, actor: str = "agent",
    ) -> None:
        """Raise ValueError if transitioning to new_status isn't allowed."""
        if new_status == TaskStatus.DONE:
            if not task.all_criteria_met():
                unmet = task.unmet_criteria()
                raise ValueError(
                    f"cannot mark task {task.id!r} done — unmet acceptance criteria: {unmet}"
                )
            if task.review_gate != ReviewGate.NONE:
                if task.status != TaskStatus.REVIEW:
                    raise ValueError(
                        f"cannot mark task {task.id!r} done directly from {task.status.value!r} — "
                        f"move it to 'review' first (review_gate={task.review_gate.value!r}; "
                        f"set review_gate to 'none' to skip review for this task)"
                    )
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
        """Return task.dependencies entries that aren't done yet."""
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
        """Undo a previous mark_criterion_met."""
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

    def _must_get(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} not found")
        return task

    def _save(self, task: Task) -> None:
        with self._write_lock:
            data = json.dumps(task_to_dict(task))
            self._conn.execute(
                """
                INSERT INTO tasks (id, status, project, assigned_to, updated_at, data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    project = excluded.project,
                    assigned_to = excluded.assigned_to,
                    updated_at = excluded.updated_at,
                    data = excluded.data
                """,
                (
                    task.id,
                    task.status.value,
                    task.project,
                    task.assigned_to,
                    task.updated_at,
                    data,
                ),
            )
            self._conn.commit()

    def _load_json(self, raw: str) -> Task | None:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or "id" not in data:
                return None
            return task_from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None
