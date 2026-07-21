"""Tests for the YAML task store."""

import tempfile
from pathlib import Path

import pytest

from agent_knots.task.models import (
    Blocker,
    Priority,
    ProgressEntry,
    ReviewGate,
    Step,
    Task,
    TaskStatus,
    new_task_id,
)
from agent_knots.task.store import TaskStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield TaskStore(Path(d))


@pytest.fixture
def sample_task():
    return Task(
        id=new_task_id(),
        title="Add login page",
        description="Implement a login form with validation.",
        status=TaskStatus.OPEN,
        priority=Priority.HIGH,
        tags=["frontend", "auth"],
        acceptance_criteria=[
            "User can enter email and password",
            "Invalid credentials show error message",
            "Successful login redirects to dashboard",
        ],
    )


class TestCRUD:
    def test_create_and_get(self, store, sample_task):
        store.create(sample_task)
        fetched = store.get(sample_task.id)
        assert fetched is not None
        assert fetched.title == "Add login page"
        assert fetched.priority == Priority.HIGH

    def test_create_duplicate_fails(self, store, sample_task):
        store.create(sample_task)
        with pytest.raises(ValueError, match="already exists"):
            store.create(sample_task)

    def test_review_gate_defaults_to_manual(self, store, sample_task):
        store.create(sample_task)
        fetched = store.get(sample_task.id)
        assert fetched.review_gate == ReviewGate.MANUAL

    def test_review_gate_round_trips(self, store, sample_task):
        sample_task.review_gate = ReviewGate.AUTO
        store.create(sample_task)
        fetched = store.get(sample_task.id)
        assert fetched.review_gate == ReviewGate.AUTO

    def test_get_missing(self, store):
        assert store.get("nonexistent") is None

    def test_list_empty(self, store):
        assert store.list() == []

    def test_list_all(self, store):
        t1 = Task(id=new_task_id(), title="Task 1")
        t2 = Task(id=new_task_id(), title="Task 2")
        store.create(t1)
        store.create(t2)
        tasks = store.list()
        assert len(tasks) == 2

    def test_list_filter_by_status(self, store):
        t1 = Task(id=new_task_id(), title="Done task", status=TaskStatus.DONE)
        t2 = Task(id=new_task_id(), title="Open task", status=TaskStatus.OPEN)
        store.create(t1)
        store.create(t2)
        assert len(store.list(status="done")) == 1
        assert len(store.list(status="open")) == 1

    def test_list_filter_by_project(self, store):
        t1 = Task(id=new_task_id(), title="A", project="proj1")
        t2 = Task(id=new_task_id(), title="B", project="proj2")
        store.create(t1)
        store.create(t2)
        assert len(store.list(project="proj1")) == 1

    def test_list_filter_by_tags(self, store):
        t1 = Task(id=new_task_id(), title="A", tags=["frontend"])
        t2 = Task(id=new_task_id(), title="B", tags=["backend"])
        store.create(t1)
        store.create(t2)
        assert len(store.list(tags=["frontend"])) == 1

    def test_list_limit(self, store):
        for i in range(5):
            store.create(Task(id=new_task_id(), title=f"Task {i}"))
        assert len(store.list(limit=3)) == 3

    def test_update(self, store, sample_task):
        store.create(sample_task)
        sample_task.title = "Updated title"
        store.update(sample_task)
        fetched = store.get(sample_task.id)
        assert fetched.title == "Updated title"

    def test_update_missing_fails(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.update(Task(id="fake", title="Nope"))

    def test_delete(self, store, sample_task):
        store.create(sample_task)
        store.delete(sample_task.id)
        assert store.get(sample_task.id) is None

    def test_delete_missing_fails(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.delete("fake")


class TestProgress:
    def test_log_progress(self, store, sample_task):
        store.create(sample_task)
        entry = ProgressEntry(
            entry="Started work on login form.",
            status=TaskStatus.IN_PROGRESS,
            caller="agent:test",
        )
        task = store.log_progress(sample_task.id, entry)
        assert len(task.progress) == 1
        assert task.status == TaskStatus.IN_PROGRESS

    def test_log_progress_with_blocker(self, store, sample_task):
        store.create(sample_task)
        entry = ProgressEntry(
            entry="Need API endpoint.",
            status=TaskStatus.BLOCKED,
            blocker=Blocker(description="API not ready", question="Deploy API first?"),
            caller="agent:test",
        )
        task = store.log_progress(sample_task.id, entry)
        assert task.status == TaskStatus.BLOCKED
        assert task.progress[0].blocker is not None
        assert task.progress[0].blocker.description == "API not ready"


class TestOperations:
    def test_assign(self, store, sample_task):
        store.create(sample_task)
        task = store.assign(sample_task.id, "agent-123")
        assert task.assigned_to == "agent-123"

    def test_unassign(self, store, sample_task):
        store.create(sample_task)
        store.assign(sample_task.id, "agent-123")
        task = store.assign(sample_task.id, "")
        assert task.assigned_to == ""

    def test_set_status(self, store, sample_task):
        store.create(sample_task)
        task = store.set_status(sample_task.id, TaskStatus.IN_PROGRESS)
        assert task.status == TaskStatus.IN_PROGRESS

    def test_set_status_terminal_fails(self, store, sample_task):
        sample_task.status = TaskStatus.DONE
        store.create(sample_task)
        with pytest.raises(ValueError, match="terminal"):
            store.set_status(sample_task.id, TaskStatus.OPEN)

    def test_add_step(self, store, sample_task):
        store.create(sample_task)
        step = Step(id="s1", title="Build form component")
        task = store.add_step(sample_task.id, step)
        assert len(task.steps) == 1
        assert task.steps[0].title == "Build form component"


class TestAcceptanceCriteria:
    def test_cannot_mark_done_with_unmet_criteria(self, store, sample_task):
        store.create(sample_task)
        with pytest.raises(ValueError, match="unmet acceptance criteria"):
            store.set_status(sample_task.id, TaskStatus.DONE)

    def test_mark_criterion_met(self, store, sample_task):
        store.create(sample_task)
        task = store.mark_criterion_met(
            sample_task.id, "User can enter email and password"
        )
        assert "User can enter email and password" in task.criteria_met
        assert not task.all_criteria_met()

    def test_can_mark_done_once_all_criteria_met(self, store, sample_task):
        store.create(sample_task)
        for c in sample_task.acceptance_criteria:
            store.mark_criterion_met(sample_task.id, c)
        task = store.set_status(sample_task.id, TaskStatus.DONE)
        assert task.status == TaskStatus.DONE

    def test_criteria_met_persists_across_reload(self, store, sample_task):
        store.create(sample_task)
        store.mark_criterion_met(sample_task.id, sample_task.acceptance_criteria[0])
        # New store instance over the same directory — forces a real disk reload.
        reloaded = TaskStore(store._dir)
        task = reloaded.get(sample_task.id)
        assert sample_task.acceptance_criteria[0] in task.criteria_met

    def test_mark_unknown_criterion_fails(self, store, sample_task):
        store.create(sample_task)
        with pytest.raises(ValueError, match="not an acceptance criterion"):
            store.mark_criterion_met(sample_task.id, "This was never a criterion")

    def test_mark_criterion_met_idempotent(self, store, sample_task):
        store.create(sample_task)
        c = sample_task.acceptance_criteria[0]
        store.mark_criterion_met(sample_task.id, c)
        task = store.mark_criterion_met(sample_task.id, c)
        assert task.criteria_met.count(c) == 1

    def test_unmark_criterion_met(self, store, sample_task):
        store.create(sample_task)
        c = sample_task.acceptance_criteria[0]
        store.mark_criterion_met(sample_task.id, c)
        task = store.unmark_criterion_met(sample_task.id, c)
        assert c not in task.criteria_met

    def test_task_with_no_criteria_can_be_marked_done(self, store):
        task = Task(id=new_task_id(), title="No criteria task", status=TaskStatus.OPEN)
        store.create(task)
        updated = store.set_status(task.id, TaskStatus.DONE)
        assert updated.status == TaskStatus.DONE

    def test_log_progress_to_done_is_gated_too(self, store, sample_task):
        """log_progress can also carry a status change — must respect the
        same gate as set_status, not bypass it."""
        store.create(sample_task)
        entry = ProgressEntry(entry="Finished.", status=TaskStatus.DONE, caller="agent:test")
        with pytest.raises(ValueError, match="unmet acceptance criteria"):
            store.log_progress(sample_task.id, entry)

    def test_log_progress_to_done_succeeds_when_criteria_met(self, store, sample_task):
        store.create(sample_task)
        for c in sample_task.acceptance_criteria:
            store.mark_criterion_met(sample_task.id, c)
        entry = ProgressEntry(entry="Finished.", status=TaskStatus.DONE, caller="agent:test")
        task = store.log_progress(sample_task.id, entry)
        assert task.status == TaskStatus.DONE


class TestTaskModel:
    def test_new_id_format(self):
        tid = new_task_id()
        assert tid.startswith("T-")
        assert len(tid) > 15  # includes random suffix

    def test_new_id_with_project(self):
        tid = new_task_id("myproj")
        assert tid.endswith("-myproj")

    def test_is_terminal(self):
        assert TaskStatus.DONE.is_terminal()
        assert TaskStatus.ABANDONED.is_terminal()
        assert not TaskStatus.OPEN.is_terminal()

    def test_is_active(self):
        assert TaskStatus.IN_PROGRESS.is_active()
        assert TaskStatus.PLANNED.is_active()
        assert not TaskStatus.DONE.is_active()

    def test_log_progress_updates_status(self):
        task = Task(id="t1", title="Test", status=TaskStatus.OPEN)
        task.log_progress(ProgressEntry(entry="Starting", status=TaskStatus.IN_PROGRESS, caller="test"))
        assert task.status == TaskStatus.IN_PROGRESS
        assert len(task.progress) == 1

    def test_all_criteria_met_true_when_empty(self):
        task = Task(id="t1", title="Test")
        assert task.all_criteria_met()
        assert task.unmet_criteria() == []

    def test_all_criteria_met_false_when_pending(self):
        task = Task(id="t1", title="Test", acceptance_criteria=["a", "b"], criteria_met=["a"])
        assert not task.all_criteria_met()
        assert task.unmet_criteria() == ["b"]

    def test_all_criteria_met_true_when_all_marked(self):
        task = Task(id="t1", title="Test", acceptance_criteria=["a", "b"], criteria_met=["a", "b"])
        assert task.all_criteria_met()
