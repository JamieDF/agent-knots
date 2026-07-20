"""Default tools given to every agent session.

These are the core coding tools from strands_tools plus the task
management tools. Agents use these to read files, write code, run
shell commands, and manage their task progress.
"""

from __future__ import annotations

# ── strands_tools ────────────────────────────────────────────────────────────

from strands_tools.editor import editor
from strands_tools.shell import shell
from strands_tools.calculator import calculator
from strands_tools.think import think

# ── task tools ───────────────────────────────────────────────────────────────

from agent_knots.task.tools import (
    add_step,
    create_task,
    list_tasks,
    log_progress,
    read_task,
    update_task,
    update_task_status,
)

# ── default set ──────────────────────────────────────────────────────────────

DEFAULT_TOOLS = [
    # File operations & shell.
    editor,
    shell,
    # Computation.
    calculator,
    # Structured thinking.
    think,
    # Task management.
    create_task,
    read_task,
    list_tasks,
    update_task_status,
    update_task,
    log_progress,
    add_step,
]


def auto_approve_tools() -> None:
    """Patch strands_tools to auto-approve confirmation prompts.

    Agents run non-interactively — there's no TTY to answer prompts.
    Uses multiple strategies:
      1. Set BYPASS_TOOL_CONSENT=true (respected by file_write, editor)
      2. Monkey-patch get_user_input in each tool module to return 'y'
    """
    import os
    os.environ["BYPASS_TOOL_CONSENT"] = "true"

    # Patch get_user_input in every strands_tools module that uses it.
    _always_yes = lambda prompt="", default="y", **kw: "y"  # noqa: E731
    try:
        import strands_tools.shell as _sh
        _sh.get_user_input = _always_yes  # type: ignore[assignment]
    except Exception:
        pass
    try:
        import strands_tools.editor as _ed
        _ed.get_user_input = _always_yes  # type: ignore[assignment]
    except Exception:
        pass
    try:
        import strands_tools.file_write as _fw
        _fw.get_user_input = _always_yes  # type: ignore[assignment]
    except Exception:
        pass
    try:
        import strands_tools.utils.user_input as _ui
        _ui.get_user_input = _always_yes  # type: ignore[assignment]
    except Exception:
        pass
