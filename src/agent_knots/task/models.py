"""Task data models — ported from internal/task/task.go.

Tasks are structured work records that survive context compaction,
session restarts, and mode swaps. They form the contract between the
user and the agent: acceptance criteria define "done", and the progress
log records every meaningful action.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class TaskStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    ABANDONED = "abandoned"

    def is_terminal(self) -> bool:
        return self in (TaskStatus.DONE, TaskStatus.ABANDONED)

    def is_active(self) -> bool:
        return self in (TaskStatus.IN_PROGRESS, TaskStatus.PLANNED)


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ReviewGate(StrEnum):
    """Controls whether a task requires a review step before DONE.

    Enforced in TaskStore._validate_transition(): unless "none", a task
    must pass through REVIEW status before DONE, and only a human actor
    (the web PATCH route) — never the agent tool path — can complete that
    final REVIEW -> DONE hop, so the same agent that did the work can't
    grant itself review approval. "auto" vs "manual" doesn't currently
    change this enforcement; the distinction is UI-only today (e.g. the
    web cockpit's "Run review now" button only shows for "auto"). Auto-
    firing a dedicated reviewer agent on entering REVIEW is not
    implemented yet.
    """
    AUTO = "auto"
    MANUAL = "manual"
    NONE = "none"


@dataclass
class Blocker:
    """Describes a state where the task cannot proceed."""
    description: str
    awaiting: str = "user"          # who/what is needed to unblock
    question: str = ""               # what to ask the user
    options: list[str] = field(default_factory=list)  # structured choices


@dataclass
class Step:
    """A sub-step within a task's plan. Can be hierarchical."""
    id: str
    title: str
    status: TaskStatus = TaskStatus.DRAFT
    notes: str = ""
    sub_steps: list[Step] = field(default_factory=list)


@dataclass
class ProgressEntry:
    """One entry in the task's progress log — the recovery point."""
    timestamp: float = field(default_factory=time.time)
    status: TaskStatus = TaskStatus.IN_PROGRESS
    entry: str = ""
    actions_taken: list[str] = field(default_factory=list)
    blocker: Blocker | None = None
    resolution: str = ""
    next_step: str = ""
    caller: str = "user"


@dataclass
class Task:
    """A unit of work tracked by the orchestrator."""

    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.DRAFT
    priority: Priority = Priority.MEDIUM
    tags: list[str] = field(default_factory=list)
    project: str = ""
    review_gate: ReviewGate = ReviewGate.MANUAL

    # What "done" means. criteria_met holds the subset of
    # acceptance_criteria that have been explicitly marked satisfied —
    # required before the task can transition to DONE.
    acceptance_criteria: list[str] = field(default_factory=list)
    criteria_met: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)

    # Structured plan.
    steps: list[Step] = field(default_factory=list)

    # Dependencies on other task IDs.
    dependencies: list[str] = field(default_factory=list)

    # Vault credentials needed.
    required_credentials: list[str] = field(default_factory=list)

    # Assignment.
    assigned_to: str = ""

    # Timestamps.
    created_at: float = field(default_factory=time.time)
    created_by: str = "user"
    updated_at: float = field(default_factory=time.time)

    # Recovery log.
    progress: list[ProgressEntry] = field(default_factory=list)

    def log_progress(self, entry: ProgressEntry) -> None:
        """Append a progress entry and bump updated_at."""
        self.progress.append(entry)
        self.updated_at = time.time()
        if entry.status:
            self.status = entry.status

    def assign(self, agent_id: str) -> None:
        """Assign this task to an agent."""
        self.assigned_to = agent_id
        self.updated_at = time.time()

    def is_terminal(self) -> bool:
        return self.status.is_terminal()

    def unmet_criteria(self) -> list[str]:
        """Acceptance criteria not yet marked met."""
        met = set(self.criteria_met)
        return [c for c in self.acceptance_criteria if c not in met]

    def all_criteria_met(self) -> bool:
        """True if every acceptance criterion has been marked met (or
        there are none)."""
        return not self.unmet_criteria()


def new_task_id(project_id: str = "") -> str:
    """Generate a unique task ID. Format: T-YYYY-MM-DD-HHMMSS-xxxx[-project]."""
    import secrets
    now = datetime.now(timezone.utc)
    rand = secrets.token_hex(2)  # 4-char random hex
    base = f"T-{now.strftime('%Y-%m-%d-%H%M%S')}-{rand}"
    if project_id:
        return f"{base}-{project_id}"
    return base
