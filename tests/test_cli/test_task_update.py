"""Tests for `agent-knots task update` — previously had zero coverage.

Regression test for a real bug: `--assign` defaulted to "" instead of
None, so the `if assign is not None` guard was always true — any
`task update` call that didn't pass --assign at all still unconditionally
called store.assign(task_id, ""), silently wiping an existing assignment
as a side effect of an unrelated field edit (e.g. --title).
"""

import importlib
from dataclasses import dataclass
from typing import Any

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@dataclass
class CliEnv:
    app: Any
    get_task_store: Any


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Isolate AGENT_KNOTS_HOME and reset cli.task's cached TaskStore
    singleton, which is otherwise created once per process and would
    leak state (and the wrong AGENT_KNOTS_HOME) across tests."""
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    from agent_knots.storage import reset_stores
    reset_stores()
    import agent_knots.cli.main as cli_main
    import agent_knots.cli.task as cli_task
    importlib.reload(cli_task)
    importlib.reload(cli_main)
    yield CliEnv(app=cli_main.app, get_task_store=cli_task._get_task_store)
    reset_stores()


def _create_task(cli_env, title: str) -> str:
    result = runner.invoke(cli_env.app, ["task", "create", title])
    assert result.exit_code == 0, result.output
    # First line is "Task created: T-...", second line echoes the title.
    return result.output.splitlines()[0].split()[-1]


class TestTaskUpdateAssign:
    def test_update_without_assign_flag_does_not_touch_assignment(self, cli_env):
        task_id = _create_task(cli_env, "Some task")
        assign_result = runner.invoke(cli_env.app, ["task", "update", task_id, "--assign", "agent-1"])
        assert assign_result.exit_code == 0, assign_result.output

        title_result = runner.invoke(cli_env.app, ["task", "update", task_id, "--title", "Renamed"])
        assert title_result.exit_code == 0, title_result.output

        task = cli_env.get_task_store().get(task_id)
        assert task.title == "Renamed"
        assert task.assigned_to == "agent-1"  # must survive the unrelated edit

    def test_update_with_explicit_empty_assign_unassigns(self, cli_env):
        task_id = _create_task(cli_env, "Some task")
        runner.invoke(cli_env.app, ["task", "update", task_id, "--assign", "agent-1"])

        result = runner.invoke(cli_env.app, ["task", "update", task_id, "--assign", ""])
        assert result.exit_code == 0, result.output

        task = cli_env.get_task_store().get(task_id)
        assert task.assigned_to == ""

    def test_update_with_assign_flag_assigns(self, cli_env):
        task_id = _create_task(cli_env, "Some task")
        result = runner.invoke(cli_env.app, ["task", "update", task_id, "--assign", "agent-2"])
        assert result.exit_code == 0, result.output

        task = cli_env.get_task_store().get(task_id)
        assert task.assigned_to == "agent-2"
