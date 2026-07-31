"""Side effects of a task's status transition — auto-stopping finished
sessions and firing configured role triggers.

Extracted from the web routes so both the human-facing PATCH endpoint
and the agent-facing task tools (task/tools.py) can trigger the same
behavior. Previously only the PATCH route did — an agent marking its
own task review/done/abandoned via update_task_status/log_progress
(the normal way an autonomous builder actually finishes) never fired
either, since those tools had no SessionManager reference and called
TaskStore directly. See task/tools.py's make_session_aware_task_tools
for how the agent-tool path now reaches these.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_knots.config import roles_file, stages_file
from agent_knots.task.models import Task
from agent_knots.workflows.models import Trigger, stage_for_status
from agent_knots.workflows.store import RolesStore, StagesStore


async def maybe_auto_stop_finished_sessions(
    session_manager: Any, new_status: str, task: Task,
) -> None:
    """Stop every session working this task once it reaches a status
    that means this round of work is over — review, done, or
    abandoned. Otherwise nothing else ever stops a finished session,
    and its git branch / auto-provisioned workdir just sit there.

    Safe to call even when one of the matching sessions is the caller's
    own currently-running session (the agent-tool path does exactly
    this) — SessionManager.stop() cancels session._task, and as long as
    this coroutine itself is running as a *different* asyncio Task than
    the one being stopped, cancelling it from here is a normal cross-task
    cancellation, not a task awaiting itself. See task/tools.py's
    _deferred_status_side_effects for why that distinction matters.
    """
    if new_status not in ("review", "done", "abandoned"):
        return
    for session in [s for s in session_manager.active if s.task_id == task.id]:
        await session_manager.stop(session.id)


def maybe_fire_role_triggers(
    session_manager: Any, old_status: str, new_status: str, task: Task,
) -> None:
    """Auto-start a session for any enabled default-agent role whose
    trigger matches this status transition (Workflows screen)."""
    stages = StagesStore(stages_file()).list()
    old_stage = stage_for_status(stages, old_status)
    new_stage = stage_for_status(stages, new_status)
    if old_stage is None or new_stage is None or old_stage.key == new_stage.key:
        return

    # Independent checks, not if/elif — tasks now start in Draft by
    # default, so a single PATCH can jump straight from draft to
    # in_progress (skipping Open entirely) and should fire *both*
    # the leaves-draft and is-started triggers, not just one.
    triggers: list[Trigger] = []
    if old_stage.key == "draft" and new_stage.key != "draft":
        triggers.append(Trigger.LEAVES_DRAFT)
    if new_stage.key == "in_progress":
        triggers.append(Trigger.IS_STARTED)
    if new_stage.key == "review":
        triggers.append(Trigger.ENTERS_REVIEW)

    for trigger in triggers:
        for role in RolesStore(roles_file()).enabled_for_trigger(trigger):
            asyncio.create_task(session_manager.start(
                mode="agent",
                model=role.model,
                system_prompt=role.prompt,
                task_id=task.id,
                task_description=f"({role.name}) {task.title}",
                # task.project is the workspace this task belongs to —
                # without it, a role-fired session gets no working
                # directory at all.
                project_id=task.project or None,
                advisory=role.advisory,
                # Only an advisory role is tool-restricted — the writer
                # keeps the full default tool set.
                allowed_tools=role.tools if role.advisory else None,
                role=role.key,
            ))
