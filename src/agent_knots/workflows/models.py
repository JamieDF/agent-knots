"""Board-stage and default-agent-role config models.

Both are small, fixed-cardinality config lists (a handful of stages,
three default roles) rather than one-file-per-item stores like tasks
or projects — a single YAML file each is simpler and matches how the
Workflows screen edits them (the whole list at once).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Trigger(StrEnum):
    """When a default agent role fires automatically."""
    LEAVES_DRAFT = "leaves_draft"
    IS_STARTED = "is_started"
    ENTERS_REVIEW = "enters_review"
    MANUAL = "manual"


@dataclass
class Stage:
    """A board column. statuses maps one or more TaskStatus values onto
    this column (e.g. "Open" covers both open and planned)."""
    key: str
    label: str
    statuses: list[str] = field(default_factory=list)
    enabled: bool = True
    required: bool = False  # e.g. draft/done can't be disabled


@dataclass
class Role:
    """A default agent (Planner/Builder/Reviewer) that can auto-fire on
    a task-status trigger. Disabled by default — auto-firing a real
    agent session has real API cost, so this is opt-in, not a default
    a new install silently starts spending money on."""
    key: str
    name: str
    icon: str
    description: str
    model: str = ""  # "" = use the global default model
    trigger: Trigger = Trigger.MANUAL
    prompt: str = ""
    # Tool names this role's session is restricted to (see
    # ModeInterventionHandler / Session.allowed_tools) when advisory is
    # True. Ignored for a non-advisory role — the writer gets the full
    # default tool set, unrestricted.
    tools: list[str] = field(default_factory=list)
    enabled: bool = False
    # An advisory role shares the task's existing writer session's
    # working tree read-only rather than getting its own branch —
    # see SessionManager._ensure_branch and the tool allowlist above,
    # which together are what make sharing that tree safe.
    advisory: bool = False


DEFAULT_STAGES: list[Stage] = [
    Stage(key="draft", label="Draft", statuses=["draft"], enabled=True, required=True),
    Stage(key="open", label="Open", statuses=["open", "planned"], enabled=True),
    Stage(key="in_progress", label="In progress", statuses=["in_progress", "blocked"], enabled=True),
    Stage(key="review", label="Review", statuses=["review"], enabled=True),
    Stage(key="done", label="Done", statuses=["done"], enabled=True, required=True),
    Stage(key="abandoned", label="Abandoned", statuses=["abandoned"], enabled=False),
]

DEFAULT_ROLES: list[Role] = [
    Role(
        key="planner", name="Planner", icon="◆",
        description="Drafts task descriptions, criteria, and steps when a task leaves Draft.",
        trigger=Trigger.LEAVES_DRAFT,
        prompt="You are a planning agent. Read the task and, if its description, "
               "acceptance criteria, or steps are incomplete, fill them in using the "
               "task tools. Do not write or edit code.",
        tools=["read_task", "update_task", "add_step"],
    ),
    Role(
        key="builder", name="Builder", icon="⚒",
        description="Works the task once it's started.",
        trigger=Trigger.IS_STARTED,
        prompt="You are an autonomous coding agent. Work through the task "
               "systematically, logging progress after every meaningful action.",
        tools=["editor", "shell", "log_progress", "update_task_status", "mark_criterion_met"],
    ),
    Role(
        key="reviewer", name="Reviewer", icon="🛡",
        description="Reviews the task when it enters Review.",
        trigger=Trigger.ENTERS_REVIEW,
        prompt="You are a code reviewer. Verify each acceptance criterion is "
               "actually met before marking it, then log your findings. Do not "
               "make changes unless asked.",
        tools=["read_task", "mark_criterion_met", "log_progress"],
        advisory=True,
    ),
]


def stage_for_status(stages: list[Stage], status: str) -> Stage | None:
    return next((s for s in stages if status in s.statuses), None)
