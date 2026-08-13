"""Tests for the playground manifest — a demo repo's shipped tasks.

The round trip is the whole feature: tasks exported on the machine that
built the demo have to arrive on a stranger's machine still describing
the same work, still pointing at the same branches.
"""

from pathlib import Path

import pytest

from agent_knots.gitutil import session_branch_name
from agent_knots.playground import (
    MANIFEST_VERSION,
    ManifestError,
    build_manifest,
    has_manifest,
    manifest_path,
    read_manifest,
    write_manifest,
)
from agent_knots.task.models import Priority, ProgressEntry, Task, TaskStatus
from agent_knots.yamlfile import atomic_write_yaml


def _task(task_id: str, title: str, status: TaskStatus, **kw) -> Task:
    t = Task(
        id=task_id, title=title, status=status, project="built-here",
        priority=kw.pop("priority", Priority.MEDIUM), **kw,
    )
    t.progress.append(ProgressEntry(entry=f"[editor_tool] did {title}"))
    return t


@pytest.fixture
def tasks():
    return [
        _task("T-2026-01-01-000001-aaaa-demo", "Scaffold the Vite app", TaskStatus.DONE,
              acceptance_criteria=["Builds cleanly"], criteria_met=["Builds cleanly"]),
        _task("T-2026-01-01-000002-bbbb-demo", "Add the contrast checker", TaskStatus.REVIEW,
              acceptance_criteria=["WCAG AA reported"], assigned_to="sess-abc123"),
        _task("T-2026-01-01-000003-cccc-demo", "Shareable palette URLs", TaskStatus.DRAFT,
              dependencies=["T-2026-01-01-000002-bbbb-demo"]),
    ]


class TestBuildManifest:
    def test_versioned(self, tasks):
        assert build_manifest(tasks)["version"] == MANIFEST_VERSION

    def test_strips_assigned_to(self, tasks):
        """It holds a session id from the machine that built the demo.
        Imported elsewhere it would show a live agent that never was."""
        assert any(t.assigned_to for t in tasks), "fixture should exercise this"
        for entry in build_manifest(tasks)["tasks"]:
            assert "assigned_to" not in entry

    def test_strips_project(self, tasks):
        """Rewritten to the importing workspace, so the exporter's id is
        noise."""
        for entry in build_manifest(tasks)["tasks"]:
            assert "project" not in entry

    def test_keeps_progress(self, tasks):
        """The real agent log is the most convincing part of the demo —
        a task that shows what actually happened reads very differently
        from one that only claims a status."""
        for entry in build_manifest(tasks)["tasks"]:
            assert entry["progress"], entry["title"]

    def test_ordered_by_creation(self, tasks):
        titles = [e["title"] for e in build_manifest(list(reversed(tasks)))["tasks"]]
        assert titles == [t.title for t in tasks]


class TestRoundTrip:
    def test_preserves_the_work(self, tasks, tmp_path):
        write_manifest(tmp_path, tasks)
        imported = {t.id: t for t in read_manifest(tmp_path, "local-ws")}

        assert set(imported) == {t.id for t in tasks}
        for original in tasks:
            got = imported[original.id]
            assert got.title == original.title
            assert got.status == original.status
            assert got.acceptance_criteria == original.acceptance_criteria
            assert got.criteria_met == original.criteria_met
            assert got.dependencies == original.dependencies
            assert len(got.progress) == len(original.progress)

    def test_rebinds_to_the_local_workspace(self, tasks, tmp_path):
        write_manifest(tmp_path, tasks)
        for t in read_manifest(tmp_path, "local-ws"):
            assert t.project == "local-ws"
            assert t.assigned_to == ""

    def test_branch_names_survive(self, tasks, tmp_path):
        """The constraint the in-review demo rests on. A branch is
        derived from sha1(task_id)[:6] plus the title slug, so the
        branch pushed alongside the demo only lines up with its task if
        both id and title come back unchanged."""
        write_manifest(tmp_path, tasks)
        imported = {t.id: t for t in read_manifest(tmp_path, "local-ws")}

        for original in tasks:
            got = imported[original.id]
            assert session_branch_name(got.id, got.title, "") == \
                session_branch_name(original.id, original.title, "")

    def test_dependencies_still_resolve(self, tasks, tmp_path):
        """Preserving ids is what lets dependencies survive without any
        remapping pass."""
        write_manifest(tmp_path, tasks)
        imported = read_manifest(tmp_path, "local-ws")
        ids = {t.id for t in imported}
        for t in imported:
            for dep in t.dependencies:
                assert dep in ids


class TestManifestErrors:
    def test_missing_file(self, tmp_path):
        assert has_manifest(tmp_path) is False
        with pytest.raises(ManifestError, match="no playground manifest"):
            read_manifest(tmp_path, "ws")

    def test_written_manifest_is_detected(self, tasks, tmp_path):
        write_manifest(tmp_path, tasks)
        assert has_manifest(tmp_path) is True
        assert manifest_path(tmp_path).parent.name == ".agent-knots"

    def test_future_version_refused(self, tasks, tmp_path):
        """Refuse outright rather than half-importing a shape we don't
        understand."""
        path = manifest_path(tmp_path)
        path.parent.mkdir(parents=True)
        atomic_write_yaml(path, {"version": MANIFEST_VERSION + 1, "tasks": []})
        with pytest.raises(ManifestError, match="newer than this agent-knots"):
            read_manifest(tmp_path, "ws")

    def test_not_a_mapping(self, tmp_path):
        path = manifest_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("- just\n- a list\n")
        with pytest.raises(ManifestError, match="not a mapping"):
            read_manifest(tmp_path, "ws")

    def test_missing_tasks_list(self, tmp_path):
        path = manifest_path(tmp_path)
        path.parent.mkdir(parents=True)
        atomic_write_yaml(path, {"version": MANIFEST_VERSION})
        with pytest.raises(ManifestError, match="no tasks list"):
            read_manifest(tmp_path, "ws")

    def test_unreadable_task_fails_the_whole_import(self, tmp_path):
        """Partial seeding would leave a board nobody can reason
        about — better to import nothing."""
        path = manifest_path(tmp_path)
        path.parent.mkdir(parents=True)
        atomic_write_yaml(path, {
            "version": MANIFEST_VERSION,
            "tasks": [{"id": "T-1", "title": "fine", "status": "draft"},
                      {"id": "T-2", "title": "broken", "status": "not-a-status"}],
        })
        with pytest.raises(ManifestError, match="task 1 is unreadable"):
            read_manifest(tmp_path, "ws")


class TestWriteManifest:
    def test_creates_the_dot_directory(self, tasks, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        written = write_manifest(repo, tasks)
        assert written == repo / ".agent-knots" / "playground.yaml"
        assert written.is_file()

    def test_overwrites_cleanly(self, tasks, tmp_path):
        write_manifest(tmp_path, tasks)
        write_manifest(tmp_path, tasks[:1])
        assert len(read_manifest(tmp_path, "ws")) == 1


def test_manifest_path_is_repo_relative(tmp_path: Path):
    assert manifest_path(tmp_path) == tmp_path / ".agent-knots" / "playground.yaml"
