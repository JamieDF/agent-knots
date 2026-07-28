"""Tests for the wastebin store — stopped-session tombstone records."""

import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from agent_knots.wastebin import WastebinEntry, WastebinStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield WastebinStore(Path(d))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """A git repo with one commit on 'main' and a second branch with a commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "checkout", "-q", "-b", "knots/some-task-abc123")
    (repo / "a.txt").write_text("one\ntwo\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "work")
    _git(repo, "checkout", "-q", "main")
    return repo


class TestAddGetList:
    def test_add_and_get_round_trip(self, store):
        store.add(WastebinEntry(session_id="s1", task_id="t1", task_title="Fix bug"))
        entry = store.get("s1")
        assert entry is not None
        assert entry.task_id == "t1"
        assert entry.task_title == "Fix bug"

    def test_get_missing_is_none(self, store):
        assert store.get("nonexistent") is None

    def test_list_newest_first(self, store):
        store.add(WastebinEntry(session_id="old", stopped_at=1.0))
        time.sleep(0.01)
        store.add(WastebinEntry(session_id="new", stopped_at=2.0))
        entries = store.list()
        assert [e.session_id for e in entries] == ["new", "old"]

    def test_list_empty(self, store):
        assert store.list() == []


class TestRetentionSweep:
    def test_list_with_no_retention_keeps_everything(self, store):
        store.add(WastebinEntry(session_id="ancient", stopped_at=1.0))
        assert len(store.list(retention_days=0)) == 1

    def test_list_purges_entries_older_than_retention(self, store):
        old_time = time.time() - 40 * 86400
        store.add(WastebinEntry(session_id="old", stopped_at=old_time))
        store.add(WastebinEntry(session_id="new", stopped_at=time.time()))

        entries = store.list(retention_days=30)

        assert [e.session_id for e in entries] == ["new"]
        assert store.get("old") is None  # actually purged, not just filtered
        assert store.get("new") is not None

    def test_sweep_never_deletes_a_branch_a_kept_entry_still_references(self, store, repo):
        old_time = time.time() - 40 * 86400
        # Two entries share a branch (task resumed, stopped twice) —
        # the older one expires, the newer one doesn't.
        store.add(WastebinEntry(
            session_id="old", branch="knots/some-task-abc123", branch_base="main",
            working_dir=str(repo), stopped_at=old_time,
        ))
        store.add(WastebinEntry(
            session_id="new", branch="knots/some-task-abc123", branch_base="main",
            working_dir=str(repo), stopped_at=time.time(),
        ))

        store.list(retention_days=30)

        # The old record is gone, but the branch itself must survive —
        # the new record still points at it.
        assert store.get("old") is None
        assert store.get("new") is not None
        result = subprocess.run(
            ["git", "branch", "--list", "knots/some-task-abc123"],
            cwd=str(repo), capture_output=True, text=True,
        )
        assert "knots/some-task-abc123" in result.stdout


class TestDelete:
    def test_delete_missing_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.delete("nonexistent")

    def test_delete_removes_the_record(self, store):
        store.add(WastebinEntry(session_id="s1"))
        store.delete("s1")
        assert store.get("s1") is None

    def test_delete_force_deletes_the_branch(self, store, repo):
        store.add(WastebinEntry(
            session_id="s1", branch="knots/some-task-abc123", branch_base="main",
            working_dir=str(repo),
        ))
        store.delete("s1")
        result = subprocess.run(
            ["git", "branch", "--list", "knots/some-task-abc123"],
            cwd=str(repo), capture_output=True, text=True,
        )
        assert "knots/some-task-abc123" not in result.stdout

    def test_delete_skips_a_protected_branch(self, store, repo):
        store.add(WastebinEntry(
            session_id="s1", branch="knots/some-task-abc123", branch_base="main",
            working_dir=str(repo),
        ))
        store.delete("s1", protected_branches={"knots/some-task-abc123"})
        result = subprocess.run(
            ["git", "branch", "--list", "knots/some-task-abc123"],
            cwd=str(repo), capture_output=True, text=True,
        )
        assert "knots/some-task-abc123" in result.stdout
        assert store.get("s1") is None  # record still removed either way

    def test_delete_rmtrees_an_auto_workdir(self, store, tmp_path):
        workdir = tmp_path / "auto-workdir"
        workdir.mkdir()
        (workdir / "output.txt").write_text("agent output\n")
        store.add(WastebinEntry(session_id="s1", working_dir=str(workdir), is_auto_workdir=True))

        store.delete("s1")

        assert not workdir.exists()

    def test_delete_never_touches_a_real_repo_working_dir(self, store, repo):
        """is_auto_workdir=False (the default for a real project repo) —
        this directory is the user's own code, never ours to rmtree."""
        store.add(WastebinEntry(session_id="s1", working_dir=str(repo), is_auto_workdir=False))
        store.delete("s1")
        assert repo.exists()
        assert (repo / "a.txt").exists()

    def test_delete_on_already_missing_branch_and_dir_does_not_raise(self, store, tmp_path):
        gone_dir = tmp_path / "already-gone"
        store.add(WastebinEntry(
            session_id="s1", branch="knots/nonexistent-branch", branch_base="main",
            working_dir=str(gone_dir), is_auto_workdir=True,
        ))
        store.delete("s1")  # should not raise
        assert store.get("s1") is None
