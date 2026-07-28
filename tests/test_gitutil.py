"""Tests for the git helpers backing per-session branches."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from agent_knots.gitutil import (
    branch_exists,
    commits_ahead,
    current_branch,
    delete_branch_if_empty,
    ensure_session_branch,
    is_dirty,
    is_repo,
    session_branch_name,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture
def repo():
    """A git repo with one commit on a branch called 'main'."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d)
        _git(path, "init", "-q", "-b", "main")
        _git(path, "config", "user.email", "test@example.com")
        _git(path, "config", "user.name", "Test")
        (path / "README.md").write_text("hello\n")
        _git(path, "add", "README.md")
        _git(path, "commit", "-qm", "initial")
        yield path


@pytest.fixture
def not_repo():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestQueries:
    def test_is_repo(self, repo, not_repo):
        assert is_repo(repo) is True
        assert is_repo(not_repo) is False

    def test_current_branch(self, repo):
        assert current_branch(repo) == "main"

    def test_current_branch_detached_is_none(self, repo):
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True,
        ).stdout.strip()
        _git(repo, "checkout", "-q", sha)
        assert current_branch(repo) is None

    def test_is_dirty(self, repo):
        assert is_dirty(repo) is False
        (repo / "README.md").write_text("changed\n")
        assert is_dirty(repo) is True

    def test_branch_exists(self, repo):
        assert branch_exists(repo, "main") is True
        assert branch_exists(repo, "nope") is False

    def test_commits_ahead(self, repo):
        _git(repo, "checkout", "-q", "-b", "feature")
        assert commits_ahead(repo, "feature", "main") == 0
        (repo / "new.txt").write_text("x\n")
        _git(repo, "add", "new.txt")
        _git(repo, "commit", "-qm", "add new")
        assert commits_ahead(repo, "feature", "main") == 1

    def test_commits_ahead_unknown_is_negative(self, repo):
        # An unanswerable question must not read as "0 commits, safe to delete".
        assert commits_ahead(repo, "does-not-exist", "main") == -1


class TestBranchNaming:
    def test_with_task(self):
        import hashlib
        short = hashlib.sha1(b"tsk-1").hexdigest()[:6]
        assert session_branch_name("tsk-1", "Fix login bug", "abc123") == f"knots/fix-login-bug-{short}"

    def test_without_task(self):
        assert session_branch_name(None, "", "abc123") == "knots/session-abc123"

    def test_deterministic(self):
        # Same task -> same branch, regardless of session id — this is
        # what makes resuming a task land back on the same branch.
        assert session_branch_name("t", "Some title", "s1") == session_branch_name("t", "Some title", "s2")

    def test_blank_title_falls_back_to_task(self):
        assert session_branch_name("tsk-1", "", "abc123").startswith("knots/task-")

    def test_title_with_punctuation_is_slugified(self):
        name = session_branch_name("tsk-1", "feat: New welcome page!", "abc123")
        assert name.startswith("knots/feat-new-welcome-page-")
        assert ":" not in name and "!" not in name and " " not in name

    def test_two_tasks_with_the_same_title_get_different_branches(self):
        a = session_branch_name("tsk-a", "Fix bug", "s1")
        b = session_branch_name("tsk-b", "Fix bug", "s1")
        assert a != b


class TestEnsureSessionBranch:
    def test_creates_and_checks_out(self, repo):
        result = ensure_session_branch(repo, "knots/t-1", "main")
        assert result.skipped_reason is None
        assert result.created is True
        assert result.name == "knots/t-1"
        assert current_branch(repo) == "knots/t-1"

    def test_existing_branch_checks_out_without_creating(self, repo):
        _git(repo, "branch", "knots/t-1")
        result = ensure_session_branch(repo, "knots/t-1", "main")
        assert result.skipped_reason is None
        assert result.created is False
        assert current_branch(repo) == "knots/t-1"

    def test_non_repo_skips(self, not_repo):
        result = ensure_session_branch(not_repo, "knots/t-1", "main")
        assert result.skipped_reason == "not a git repository"
        assert result.name is None

    def test_dirty_tree_still_branches(self, repo):
        # git checkout -b carries uncommitted work forward; nothing is lost,
        # so a dirty tree must not block branching.
        (repo / "README.md").write_text("uncommitted\n")
        result = ensure_session_branch(repo, "knots/t-1", "main")
        assert result.skipped_reason is None
        assert current_branch(repo) == "knots/t-1"
        assert (repo / "README.md").read_text() == "uncommitted\n"

    def test_bad_base_skips(self, repo):
        result = ensure_session_branch(repo, "knots/t-1", "no-such-base")
        assert result.skipped_reason is not None
        assert current_branch(repo) == "main"


class TestDeleteBranchIfEmpty:
    def test_deletes_empty_branch(self, repo):
        ensure_session_branch(repo, "knots/t-1", "main")
        assert delete_branch_if_empty(repo, "knots/t-1", "main") is True
        assert branch_exists(repo, "knots/t-1") is False
        assert current_branch(repo) == "main"

    def test_keeps_branch_with_commits(self, repo):
        ensure_session_branch(repo, "knots/t-1", "main")
        (repo / "work.txt").write_text("real work\n")
        _git(repo, "add", "work.txt")
        _git(repo, "commit", "-qm", "work")
        assert delete_branch_if_empty(repo, "knots/t-1", "main") is False
        assert branch_exists(repo, "knots/t-1") is True

    def test_unknown_branch_is_not_deleted(self, repo):
        assert delete_branch_if_empty(repo, "no-such-branch", "main") is False
