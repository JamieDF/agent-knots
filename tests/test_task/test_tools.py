"""Tests for the agent-facing task tools (task/tools.py).

Mostly covered indirectly via test_store.py (these tools are thin
wrappers over TaskStore), but validate_task_output's wiring into
create_task/update_task is new behavior worth testing directly: before
this, an invalid priority/status raised an uncaught ValueError instead
of returning a structured tool error.
"""

import tempfile
from pathlib import Path

import pytest

from agent_knots.task.tools import create_task, update_task, validate_task_output


@pytest.fixture(autouse=True)
def tasks_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("AGENT_KNOTS_HOME", d)
        yield Path(d)


class TestValidateTaskOutput:
    def test_valid_data(self):
        result = validate_task_output({"title": "Do the thing", "priority": "high"})
        assert result["valid"]

    def test_empty_title_invalid(self):
        result = validate_task_output({"title": ""})
        assert not result["valid"]
        assert "title" in result["errors"][0]

    def test_non_string_title_invalid(self):
        result = validate_task_output({"title": 123})
        assert not result["valid"]

    def test_invalid_priority(self):
        result = validate_task_output({"priority": "urgentest"})
        assert not result["valid"]
        assert "priority" in result["errors"][0]

    def test_invalid_status(self):
        result = validate_task_output({"status": "kinda-done"})
        assert not result["valid"]
        assert "status" in result["errors"][0]

    def test_empty_data_is_valid(self):
        """No fields to check means nothing to reject."""
        assert validate_task_output({})["valid"]


class TestCreateTaskValidation:
    def test_invalid_priority_returns_error_not_exception(self):
        result = create_task(title="Test", priority="not-a-real-priority")
        assert "error" in result

    def test_empty_title_returns_error(self):
        result = create_task(title="", priority="medium")
        assert "error" in result

    def test_valid_creates_task(self):
        result = create_task(title="Real task", priority="high")
        assert "error" not in result
        assert result["priority"] == "high"


class TestUpdateTaskValidation:
    def test_invalid_priority_returns_error_not_exception(self):
        created = create_task(title="Task to update", priority="medium")
        result = update_task(created["id"], priority="nonsense")
        assert "error" in result

    def test_valid_priority_update_succeeds(self):
        created = create_task(title="Task to update", priority="medium")
        result = update_task(created["id"], priority="urgent")
        assert "error" not in result
        assert result["priority"] == "urgent"

    def test_missing_task_returns_error(self):
        result = update_task("nonexistent-task-id", title="New title")
        assert "error" in result
