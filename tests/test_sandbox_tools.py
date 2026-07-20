"""Tests for sandbox_tools.py — previously zero coverage.

Covers the parts touched in the backend-cleanup pass: run_confined's cwd
binding, timeout + process-tree cleanup, and output truncation; the
sandboxed editor's path confinement and max_file_size enforcement.
"""

import tempfile
import time
from pathlib import Path

import pytest

from agent_knots.sandbox_tools import (
    make_sandboxed_editor,
    make_sandboxed_shell,
    run_confined,
)


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestRunConfined:
    def test_runs_in_given_cwd(self, workspace):
        result = run_confined("pwd", cwd=workspace)
        assert result["stdout"].strip() == workspace

    def test_captures_stdout_and_exit_code(self):
        result = run_confined("echo hello", cwd=None)
        assert result["stdout"].strip() == "hello"
        assert result["exit_code"] == 0

    def test_nonzero_exit_code_is_not_an_error(self):
        result = run_confined("exit 3", cwd=None)
        assert "error" not in result
        assert result["exit_code"] == 3

    def test_timeout_kills_process_and_reports_error(self):
        start = time.time()
        result = run_confined("sleep 30", cwd=None, timeout=1)
        elapsed = time.time() - start
        assert "timed out" in result["error"]
        assert elapsed < 10  # didn't wait out the full sleep

    def test_output_truncated_when_over_limit(self):
        cmd = "python3 -c \"print('x' * 200, end='')\""
        result = run_confined(cmd, cwd=None, max_output=50)
        assert len(result["stdout"]) < 200
        assert "truncated" in result["stdout"]

    def test_output_not_truncated_when_under_limit(self):
        result = run_confined("echo short", cwd=None, max_output=1000)
        assert "truncated" not in result["stdout"]

    def test_no_truncation_when_limit_not_set(self):
        cmd = "python3 -c \"print('x' * 200, end='')\""
        result = run_confined(cmd, cwd=None)
        assert len(result["stdout"]) == 200


class TestSandboxedShell:
    def test_defaults_cwd_to_workspace(self, workspace):
        shell = make_sandboxed_shell(workspace)
        result = shell("pwd")
        assert result["stdout"].strip() == workspace

    def test_respects_max_output(self, workspace):
        shell = make_sandboxed_shell(workspace, max_output=10)
        result = shell("python3 -c \"print('x' * 100, end='')\"")
        assert len(result["stdout"]) < 100


class TestSandboxedEditor:
    def test_write_then_read(self, workspace):
        editor = make_sandboxed_editor(workspace)
        w = editor(path="notes.txt", content="hello", action="write")
        assert w["status"] == "ok"
        r = editor(path="notes.txt", action="read")
        assert r["content"] == "hello"

    def test_path_traversal_rejected(self, workspace):
        editor = make_sandboxed_editor(workspace)
        result = editor(path="../../etc/passwd", action="read")
        assert "error" in result
        assert "outside the workspace" in result["error"]

    def test_write_over_max_file_size_rejected(self, workspace):
        editor = make_sandboxed_editor(workspace, max_file_size=10)
        result = editor(path="big.txt", content="x" * 100, action="write")
        assert "error" in result
        assert not (Path(workspace) / "big.txt").exists()

    def test_write_under_max_file_size_succeeds(self, workspace):
        editor = make_sandboxed_editor(workspace, max_file_size=1000)
        result = editor(path="small.txt", content="ok", action="write")
        assert result["status"] == "ok"

    def test_list_directory(self, workspace):
        (Path(workspace) / "a.txt").write_text("a")
        editor = make_sandboxed_editor(workspace)
        result = editor(path=".", action="list")
        assert any(f["name"] == "a.txt" for f in result["files"])
