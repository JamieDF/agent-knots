"""Tests for sandbox_tools.py — previously zero coverage.

Covers the parts touched in the backend-cleanup pass: run_confined's cwd
binding, timeout + process-tree cleanup, and output truncation; the
sandboxed editor's path confinement and max_file_size enforcement.
"""

import os
import tempfile
import time
from pathlib import Path

import pytest

from agent_knots.sandbox_tools import (
    kill_background_process,
    make_sandboxed_editor,
    make_sandboxed_shell,
    run_background,
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


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class TestRunBackground:
    """background=true is the fix for agents having to hand-roll `nohup
    cmd &` to keep a dev server alive past the shell tool's timeout-kill
    — see run_confined's docstring / the RLIMIT_AS history in this file
    for the surrounding context on why long-running processes need a
    real first-class path instead of a shell trick."""

    def test_returns_immediately_without_waiting_for_the_process(self):
        start = time.time()
        result = run_background("sleep 5", cwd=None)
        elapsed = time.time() - start
        assert elapsed < 2  # didn't block for anything close to the 5s sleep
        kill_background_process(result["pid"])

    def test_process_is_still_running_after_call_returns(self):
        result = run_background("sleep 5", cwd=None)
        try:
            assert _is_alive(result["pid"])
        finally:
            kill_background_process(result["pid"])

    def test_runs_in_given_cwd(self, workspace):
        result = run_background("pwd", cwd=workspace)
        time.sleep(0.3)
        assert Path(result["log_file"]).read_text().strip() == workspace

    def test_log_file_captures_output(self):
        result = run_background("echo hello-background", cwd=None)
        time.sleep(0.3)
        assert "hello-background" in Path(result["log_file"]).read_text()

    def test_kill_background_process_terminates_it(self):
        result = run_background("sleep 30", cwd=None)
        assert _is_alive(result["pid"])
        kill_background_process(result["pid"])
        time.sleep(0.3)
        assert not _is_alive(result["pid"])

    def test_kill_background_process_on_already_dead_pid_does_not_raise(self):
        result = run_background("true", cwd=None)
        time.sleep(0.3)
        kill_background_process(result["pid"])  # already exited — should be a no-op


class TestSandboxedShell:
    def test_defaults_cwd_to_workspace(self, workspace):
        shell = make_sandboxed_shell(workspace)
        result = shell("pwd")
        assert result["stdout"].strip() == workspace

    def test_respects_max_output(self, workspace):
        shell = make_sandboxed_shell(workspace, max_output=10)
        result = shell("python3 -c \"print('x' * 100, end='')\"")
        assert len(result["stdout"]) < 100

    def test_background_true_returns_immediately_and_is_not_killed(self, workspace):
        shell = make_sandboxed_shell(workspace)
        start = time.time()
        result = shell("sleep 5", background=True)
        elapsed = time.time() - start
        assert elapsed < 2
        assert _is_alive(result["pid"])
        kill_background_process(result["pid"])

    def test_background_true_records_pid_in_tracking_list(self, workspace):
        pids: list[int] = []
        shell = make_sandboxed_shell(workspace, background_pids=pids)
        result = shell("sleep 5", background=True)
        assert pids == [result["pid"]]
        kill_background_process(result["pid"])

    def test_background_false_is_unaffected(self, workspace):
        pids: list[int] = []
        shell = make_sandboxed_shell(workspace, background_pids=pids)
        result = shell("echo hi")
        assert result["stdout"].strip() == "hi"
        assert pids == []


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
