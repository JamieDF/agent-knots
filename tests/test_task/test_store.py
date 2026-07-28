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

    def test_log_progress_role_round_trips(self, store, sample_task):
        """role distinguishes an advisory agent's findings from the
        writer's own progress entries once more than one session
        reports on a task — must survive a save/reload, not just live
        on the in-memory object."""
        store.create(sample_task)
        store.log_progress(sample_task.id, ProgressEntry(
            entry="Found an unhandled edge case.", caller="sess-reviewer", role="reviewer",
        ))
        reloaded = store.get(sample_task.id)
        assert reloaded.progress[0].role == "reviewer"

    def test_log_progress_role_defaults_empty(self, store, sample_task):
        store.create(sample_task)
        store.log_progress(sample_task.id, ProgressEntry(entry="Did a thing."))
        reloaded = store.get(sample_task.id)
        assert reloaded.progress[0].role == ""

    def test_concurrent_log_progress_loses_no_entries(self, store, sample_task):
        """Regression guard for the race a writer session and N advisory
        agents reporting on the same task would otherwise hit: log_progress
        is read-modify-write, so interleaved calls without a lock silently
        drop whichever entry lost the race."""
        import threading

        store.create(sample_task)
        n = 20
        barrier = threading.Barrier(n)

        def log(i: int) -> None:
            barrier.wait()
            store.log_progress(sample_task.id, ProgressEntry(entry=f"entry-{i}", caller=f"s{i}"))

        threads = [threading.Thread(target=log, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        reloaded = store.get(sample_task.id)
        assert len(reloaded.progress) == n
        assert {p.entry for p in reloaded.progress} == {f"entry-{i}" for i in range(n)}


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

    def test_set_status_reopen_terminal(self, store, sample_task):
        """Done/Abandoned tasks can be reopened — terminal is no longer a
        one-way trap. The old blanket ban on changing terminal tasks was
        removed so a human can drag a Done card back to In Progress."""
        sample_task.status = TaskStatus.DONE
        store.create(sample_task)
        task = store.set_status(sample_task.id, TaskStatus.OPEN, actor="human")
        assert task.status == TaskStatus.OPEN

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
        store.set_status(sample_task.id, TaskStatus.REVIEW)  # workflow requires review before done
        # actor="human": isolating the criteria gate from the separate
        # human-must-close-review-out gate covered below.
        task = store.set_status(sample_task.id, TaskStatus.DONE, actor="human")
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
        store.set_status(task.id, TaskStatus.REVIEW)  # workflow requires review before done
        # actor="human" isolates "no criteria doesn't block done" from the
        # actor gate covered by test_agent_cannot_self_approve_done below.
        updated = store.set_status(task.id, TaskStatus.DONE, actor="human")
        assert updated.status == TaskStatus.DONE

    def test_agent_cannot_self_approve_done_even_with_no_criteria(self, store):
        """Regression: a task with zero acceptance criteria used to sail
        straight through review to done with nothing but the same agent
        calling set_status('review') then set_status('done') back to back
        — no independent review ever actually happened. review_gate
        (default "manual") now requires a human actor for the final hop,
        regardless of how many criteria there are."""
        task = Task(id=new_task_id(), title="No criteria task", status=TaskStatus.OPEN)
        store.create(task)
        store.set_status(task.id, TaskStatus.REVIEW)
        with pytest.raises(ValueError, match="requires a human to complete"):
            store.set_status(task.id, TaskStatus.DONE)  # actor defaults to "agent"

    def test_agent_cannot_self_approve_done_with_auto_review_gate(self, store, sample_task):
        """Same gate applies to review_gate="auto", not just "manual" —
        auto-review still means a human clicks "Run review now", not that
        the agent itself gets to decide the review passed."""
        sample_task.review_gate = ReviewGate.AUTO
        store.create(sample_task)
        for c in sample_task.acceptance_criteria:
            store.mark_criterion_met(sample_task.id, c)
        store.set_status(sample_task.id, TaskStatus.REVIEW)
        with pytest.raises(ValueError, match="requires a human to complete"):
            store.set_status(sample_task.id, TaskStatus.DONE)

    def test_cannot_skip_review_straight_to_done(self, store):
        """The one guard that doesn't depend on acceptance criteria at
        all — even a task with none must still pass through review,
        unless it opts out via review_gate='none'."""
        task = Task(id=new_task_id(), title="No criteria task", status=TaskStatus.IN_PROGRESS)
        store.create(task)
        with pytest.raises(ValueError, match="move it to 'review' first"):
            store.set_status(task.id, TaskStatus.DONE)

    def test_review_gate_none_allows_skipping_review(self, store):
        task = Task(id=new_task_id(), title="Trivial task", status=TaskStatus.IN_PROGRESS, review_gate=ReviewGate.NONE)
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

    def test_log_progress_to_done_still_requires_a_human(self, store, sample_task):
        """log_progress has no way to pass actor="human" — it's only ever
        called from the agent tool (task/tools.py), never a human-facing
        route — so a done transition through it always hits the same
        agent-can't-self-approve gate as set_status, even with every
        criterion met and the task already in review."""
        store.create(sample_task)
        for c in sample_task.acceptance_criteria:
            store.mark_criterion_met(sample_task.id, c)
        store.set_status(sample_task.id, TaskStatus.REVIEW)  # workflow requires review before done
        entry = ProgressEntry(entry="Finished.", status=TaskStatus.DONE, caller="agent:test")
        with pytest.raises(ValueError, match="requires a human to complete"):
            store.log_progress(sample_task.id, entry)

    def test_log_progress_to_done_succeeds_with_review_gate_none(self, store):
        """The one way log_progress *can* reach done directly: the task
        opted out of review entirely."""
        task = Task(id=new_task_id(), title="Trivial task", status=TaskStatus.IN_PROGRESS, review_gate=ReviewGate.NONE)
        store.create(task)
        entry = ProgressEntry(entry="Finished.", status=TaskStatus.DONE, caller="agent:test")
        task = store.log_progress(task.id, entry)
        assert task.status == TaskStatus.DONE


class TestDependencies:
    def test_unmet_dependencies_empty_when_none_declared(self, store, sample_task):
        store.create(sample_task)
        assert store.unmet_dependencies(sample_task) == []

    def test_unmet_dependencies_lists_unfinished_blockers(self, store):
        blocker = Task(id=new_task_id(), title="Blocker task", status=TaskStatus.OPEN)
        store.create(blocker)
        task = Task(id=new_task_id(), title="Blocked task", status=TaskStatus.OPEN, dependencies=[blocker.id])
        store.create(task)
        unmet = store.unmet_dependencies(task)
        assert [t.id for t in unmet] == [blocker.id]

    def test_unmet_dependencies_empty_once_blocker_done(self, store):
        blocker = Task(id=new_task_id(), title="Blocker task", status=TaskStatus.IN_PROGRESS, review_gate=ReviewGate.NONE)
        store.create(blocker)
        store.set_status(blocker.id, TaskStatus.DONE, actor="human")
        task = Task(id=new_task_id(), title="Blocked task", status=TaskStatus.OPEN, dependencies=[blocker.id])
        store.create(task)
        assert store.unmet_dependencies(task) == []

    def test_dangling_dependency_id_does_not_block(self, store):
        """A dependency pointing at a deleted/never-existed task shouldn't
        lock the dependent task forever."""
        task = Task(id=new_task_id(), title="Blocked task", status=TaskStatus.OPEN, dependencies=["T-does-not-exist"])
        store.create(task)
        assert store.unmet_dependencies(task) == []

    def test_cannot_start_task_blocked_by_unfinished_dependency(self, store):
        blocker = Task(id=new_task_id(), title="Blocker task", status=TaskStatus.OPEN)
        store.create(blocker)
        task = Task(id=new_task_id(), title="Blocked task", status=TaskStatus.OPEN, dependencies=[blocker.id])
        store.create(task)
        with pytest.raises(ValueError, match="blocked by unfinished dependencies"):
            store.set_status(task.id, TaskStatus.IN_PROGRESS)

    def test_can_start_task_once_dependency_done(self, store):
        blocker = Task(id=new_task_id(), title="Blocker task", status=TaskStatus.IN_PROGRESS, review_gate=ReviewGate.NONE)
        store.create(blocker)
        store.set_status(blocker.id, TaskStatus.DONE, actor="human")
        task = Task(id=new_task_id(), title="Blocked task", status=TaskStatus.OPEN, dependencies=[blocker.id])
        store.create(task)
        updated = store.set_status(task.id, TaskStatus.IN_PROGRESS)
        assert updated.status == TaskStatus.IN_PROGRESS


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
