"""Tests for the wastebin store — stopped-session tombstone records."""

import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from agent_knots.wastebin import WastebinEntry, WastebinStore
from agent_knots.yamlfile import atomic_write_yaml, safe_read_yaml


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


class TestHistory:
    """History lives in a separate <id>.history.json, not the metadata
    YAML — list()/get() must stay cheap regardless of how large a
    session's transcript is, since they're read on every poll from
    several screens (Task Detail's Past Sessions, the Review task list,
    the Settings Wastebin card)."""

    def test_add_with_history_then_get_history_round_trips(self, store):
        history = [{"type": "message", "session_id": "s1", "message": "hi"}]
        store.add(WastebinEntry(session_id="s1"), history=history)
        assert store.get_history("s1") == history

    def test_get_history_empty_when_none_was_ever_written(self, store):
        store.add(WastebinEntry(session_id="s1"))
        assert store.get_history("s1") == []

    def test_get_history_empty_for_unknown_session(self, store):
        assert store.get_history("nonexistent") == []

    def test_metadata_entry_has_no_history_attribute(self, store):
        """Structural guarantee, not just a behavioral one — list()/get()
        return WastebinEntry, which no longer has a history field at
        all, so there's no way for either to accidentally deserialize
        it even if a caller tried to read entry.history."""
        store.add(WastebinEntry(session_id="s1"), history=[{"type": "message"}])
        assert not hasattr(store.get("s1"), "history")
        assert not hasattr(store.list()[0], "history")

    def test_delete_removes_the_history_file_too(self, store, tmp_path):
        store.add(WastebinEntry(session_id="s1"), history=[{"type": "message"}])
        history_path = store._history_path("s1")
        assert history_path.exists()
        store.delete("s1")
        assert not history_path.exists()

    def test_list_does_not_require_a_history_file_to_exist(self, store):
        """add() without a history arg (or with an empty list) writes no
        history file at all — list() must not choke on that."""
        store.add(WastebinEntry(session_id="s1"))
        entries = store.list()
        assert len(entries) == 1
        assert store.get_history("s1") == []

    def test_get_migrates_a_legacy_entry_with_embedded_history(self, store):
        """Entries written before history moved out of the metadata
        YAML (pre-migration) had it inline — get() must split it out to
        the sibling file and strip it from the metadata on first read,
        so every read after that one is back to being cheap."""
        legacy = {
            "session_id": "s1", "task_id": "t1", "task_title": "Old entry",
            "history": [{"type": "message", "message": "from before the split"}],
        }
        atomic_write_yaml(store._path("s1"), legacy)

        entry = store.get("s1")
        assert entry is not None
        assert entry.task_title == "Old entry"
        assert not hasattr(entry, "history")
        assert store.get_history("s1") == [{"type": "message", "message": "from before the split"}]

        # The metadata file itself no longer has history embedded.
        on_disk = safe_read_yaml(store._path("s1"))
        assert "history" not in on_disk

    def test_list_also_migrates_a_legacy_entry(self, store):
        legacy = {"session_id": "s1", "history": [{"type": "message"}]}
        atomic_write_yaml(store._path("s1"), legacy)

        entries = store.list()
        assert len(entries) == 1
        assert store.get_history("s1") == [{"type": "message"}]
        assert "history" not in safe_read_yaml(store._path("s1"))


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
