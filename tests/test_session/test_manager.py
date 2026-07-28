"""Tests for SessionManager and Session."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from agent_knots.events import Event, EventType, ToolCall
from agent_knots.session.manager import Session, SessionManager


@pytest.fixture
def sessions_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def agent_knots_home(tmp_path, monkeypatch):
    """Isolate AGENT_KNOTS_HOME so tests never touch the real user config,
    and reset the global runtime-type setting between tests."""
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    from agent_knots.session.runtime import set_runtime_type
    set_runtime_type("inprocess")
    yield tmp_path


class TestSession:
    def test_default_id_is_generated(self):
        s = Session()
        assert len(s.id) == 12
        assert s.id.isalnum()

    def test_id_can_be_set(self):
        s = Session(id="abc123")
        assert s.id == "abc123"

    def test_defaults(self):
        s = Session()
        assert s.mode == "agent"
        assert s.task_id is None
        assert s.project_id is None
        assert s.tokens_used == 0
        assert s.cost_usd == 0.0

    def test_running_when_no_task(self):
        s = Session()
        assert not s.running

    @pytest.mark.asyncio
    async def test_cancel_no_task(self):
        s = Session()
        await s.cancel()  # should not raise

    @pytest.mark.asyncio
    async def test_broadcast_delivers_to_subscriber(self):
        s = Session()
        q = s.subscribe()
        s._broadcast(Event(type=EventType.MESSAGE, session_id=s.id, message="hi"))
        evt = await q.get()
        assert evt.message == "hi"

    @pytest.mark.asyncio
    async def test_broadcast_fans_out_to_multiple_subscribers(self):
        """Regression test: a second SSE viewer used to race the first
        for events on one shared queue and silently lose them."""
        s = Session()
        q1 = s.subscribe()
        q2 = s.subscribe()
        s._broadcast(Event(type=EventType.MESSAGE, session_id=s.id, message="hi"))
        assert (await q1.get()).message == "hi"
        assert (await q2.get()).message == "hi"

    @pytest.mark.asyncio
    async def test_subscribe_replays_history(self):
        """A subscriber connecting after events already happened (e.g. a
        second browser tab opened mid-session) should still see them."""
        s = Session()
        s._broadcast(Event(type=EventType.MESSAGE, session_id=s.id, message="before"))
        q = s.subscribe()
        evt = await q.get()
        assert evt.message == "before"

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        s = Session()
        q = s.subscribe()
        s.unsubscribe(q)
        s._broadcast(Event(type=EventType.MESSAGE, session_id=s.id, message="hi"))
        assert q.empty()

    def test_history_bounded(self):
        s = Session()
        s._history_limit = 3
        for i in range(5):
            s._broadcast(Event(type=EventType.MESSAGE, session_id=s.id, message=str(i)))
        assert len(s._history) == 3
        assert [e.message for e in s._history] == ["2", "3", "4"]


class TestChunkToEvent:
    def test_event_chunk_skipped(self):
        """contentBlockDelta events are skipped (we use data+delta instead)."""
        evt = SessionManager._chunk_to_event("sid", {
            "event": {"contentBlockDelta": {"delta": {"text": "hello"}}},
        })
        assert evt is None

    def test_data_delta_incremental(self):
        """data+delta only emits the new portion after first call."""
        state = {}
        # First chunk: full text.
        evt = SessionManager._chunk_to_event("sid", {
            "data": "hello", "delta": {"text": "hello"},
        }, state)
        assert evt is not None
        assert evt.message == "hello"

        # Second chunk: same prefix + new text — only new emitted.
        evt = SessionManager._chunk_to_event("sid", {
            "data": "hello world", "delta": {"text": "hello world"},
        }, state)
        assert evt is not None
        assert evt.message == " world"

    def test_message_chunk(self):
        """Real Strands chunk: final message."""
        evt = SessionManager._chunk_to_event("sid", {
            "message": {"role": "assistant", "content": [{"text": "final response"}]},
        })
        assert evt is not None
        assert evt.type == EventType.MESSAGE
        assert "final response" in evt.message

    def test_thinking_split_across_multiple_deltas(self):
        """Regression: found via a real MiniMax M2.7 call. <think>...</think>
        commonly arrives split across several data+delta chunks, where only
        the FIRST fragment literally starts with "<think>". The old
        per-fragment _is_thinking() heuristic had no memory of a think
        block already being open, so every later fragment (including the
        one carrying the closing tag) was misclassified as MESSAGE — most
        of the model's actual reasoning leaked into the visible reply, tag
        literals included."""
        state: dict = {}
        evt1 = SessionManager._chunk_to_event("sid", {
            "data": "<think>\nThe user", "delta": {"text": "<think>\nThe user"},
        }, state)
        assert evt1.type == EventType.THINKING
        assert "<think>" not in evt1.message
        assert evt1.message == "\nThe user"

        # Second fragment carries the closing tag partway through, AND
        # some (whitespace) message text right after it in the very same
        # delta — this must split into two events, not get lumped into
        # one THINKING blob (that used to leak real response text into
        # the thinking bubble) or one MESSAGE blob (which would show the
        # tail of the model's reasoning as if it were the actual reply).
        full = "<think>\nThe user wants to know X.\n</think>\n\n"
        evt2 = SessionManager._chunk_to_event("sid", {
            "data": full, "delta": {"text": full},
        }, state)
        assert isinstance(evt2, list) and len(evt2) == 2
        assert evt2[0].type == EventType.THINKING
        assert "</think>" not in evt2[0].message
        assert "wants to know X" in evt2[0].message
        assert evt2[1].type == EventType.MESSAGE

        # A subsequent fragment with no tags at all is back to MESSAGE.
        full2 = full + "The answer is 4."
        evt3 = SessionManager._chunk_to_event("sid", {
            "data": full2, "delta": {"text": full2},
        }, state)
        assert evt3.type == EventType.MESSAGE
        assert evt3.message == "The answer is 4."

    def test_think_close_and_response_in_same_delta(self):
        """Regression: a real MiniMax response where the </think> close tag
        and the start of the actual reply arrived in the exact same delta
        fragment (not split across chunks like the test above) — e.g.
        "...to help</think>\\n\\nHello! I'm here...". The old code
        classified the WHOLE fragment as one type based only on the state
        from before this delta, so the real reply text after the tag got
        rendered inside the collapsed "thinking" bubble instead of as the
        actual message."""
        state = {"in_think": True}
        evt = SessionManager._chunk_to_event("sid", {
            "data": "...to help</think>\n\nHello! I'm here.",
            "delta": {"text": "...to help</think>\n\nHello! I'm here."},
        }, state)
        assert isinstance(evt, list) and len(evt) == 2
        assert evt[0].type == EventType.THINKING
        assert evt[0].message == "...to help"
        assert evt[1].type == EventType.MESSAGE
        assert evt[1].message == "\n\nHello! I'm here."
        assert state["in_think"] is False

    def test_final_message_chunk_suppressed_after_streaming(self):
        """Once a turn's text was already streamed via data+delta chunks,
        Strands' final 'message' chunk re-sends the whole thing again —
        emitting another event for it doubled every response in the UI."""
        state: dict = {}
        SessionManager._chunk_to_event("sid", {
            "data": "Hello!", "delta": {"text": "Hello!"},
        }, state)
        assert state["streamed_any"] is True

        evt = SessionManager._chunk_to_event("sid", {
            "message": {"role": "assistant", "content": [{"text": "Hello!"}]},
        }, state)
        assert evt is None

    def test_final_message_chunk_kept_when_nothing_streamed(self):
        """A provider that never sends data+delta chunks (no streaming)
        still needs its one final message chunk to actually show up."""
        state: dict = {}
        evt = SessionManager._chunk_to_event("sid", {
            "message": {"role": "assistant", "content": [{"text": "Hello!"}]},
        }, state)
        assert evt is not None
        assert evt.type == EventType.MESSAGE
        assert evt.message == "Hello!"

    def test_message_with_think(self):
        """MiniMax returns <think> tags in content."""
        evt = SessionManager._chunk_to_event("sid", {
            "message": {"role": "assistant", "content": [
                {"text": "<think>\nreasoning here\n</think>\n\nactual answer"}
            ]},
        })
        assert evt is not None
        assert evt.type == EventType.MESSAGE
        assert "actual answer" in evt.message
        assert "reasoning" not in evt.message  # thinking stripped

    def test_tool_result_success_populates_tool_result(self):
        """Regression: Event.tool_result used to be left unset entirely
        for every TOOL_RESULT event, so the frontend had no reliable way
        to tell a failed tool call from a successful one and rendered
        both identically. Strands' own status field ("success"/"error")
        is tool-agnostic — works for the shell tool's exit code as much
        as the editor/calculator/task tools, none of which have one."""
        evt = SessionManager._chunk_to_event("sid", {
            "message": {"role": "user", "content": [{"toolResult": {
                "toolUseId": "tool-1",
                "status": "success",
                "content": [{"text": "done"}],
            }}]},
        })
        assert evt is not None
        assert evt.type == EventType.TOOL_RESULT
        assert evt.tool_result is not None
        assert evt.tool_result.tool_call_id == "tool-1"
        assert evt.tool_result.exit_code == 0
        assert evt.tool_result.error == ""
        assert evt.tool_result.stdout == "done"

    def test_tool_result_error_populates_tool_result(self):
        evt = SessionManager._chunk_to_event("sid", {
            "message": {"role": "user", "content": [{"toolResult": {
                "toolUseId": "tool-2",
                "status": "error",
                "content": [{"text": "command not found"}],
            }}]},
        })
        assert evt is not None
        assert evt.tool_result is not None
        assert evt.tool_result.exit_code == 1
        assert evt.tool_result.error == "command not found"
        assert evt.tool_result.stdout == ""

    def test_result_chunk_skipped(self):
        """Real Strands chunk: result. _run_agent already broadcasts its
        own "Agent finished." once the stream loop ends — this chunk
        always precedes that, so it must produce no event of its own or
        the message doubles up ("Agent finished. Agent finished.")."""
        evt = SessionManager._chunk_to_event("sid", {
            "result": "AgentResult(...)",
        })
        assert evt is None

    def test_lifecycle_skipped(self):
        """Lifecycle bookmarks should be skipped."""
        assert SessionManager._chunk_to_event("sid", {"init_event_loop": True}) is None
        assert SessionManager._chunk_to_event("sid", {"start": True}) is None

    def test_none_chunk(self):
        assert SessionManager._chunk_to_event("sid", None) is None

    def test_string_chunk(self):
        """Strings are not valid chunks."""
        assert SessionManager._chunk_to_event("sid", "hello") is None

    def test_empty_dict(self):
        """Empty dicts produce no event."""
        assert SessionManager._chunk_to_event("sid", {}) is None


class TestSessionManager:
    def test_initial_state(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        assert mgr.active == []
        assert mgr.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_stop_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        await mgr.stop("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_stop_kills_tracked_background_processes(self, sessions_dir):
        """Regression guard: background=true shell commands (dev servers)
        are tracked on the session precisely so stop() can clean them up
        — otherwise they'd outlive the session they were started from
        forever."""
        import os

        from agent_knots.sandbox_tools import run_background

        s = Session()
        result = run_background("sleep 30", cwd=None)
        s._background_pids.append(result["pid"])

        mgr = SessionManager(sessions_dir)
        mgr._sessions[s.id] = s

        def is_alive(pid: int) -> bool:
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False

        assert is_alive(result["pid"])
        await mgr.stop(s.id)
        assert not is_alive(result["pid"])

    @pytest.mark.asyncio
    async def test_send_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            await mgr.send("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_set_mode_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            await mgr.set_mode("nonexistent", "assistant")

    @pytest.mark.asyncio
    async def test_set_autonomous_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            await mgr.set_autonomous("nonexistent", True)

    @pytest.mark.asyncio
    async def test_set_autonomous_off_interrupts_a_running_turn(self, sessions_dir):
        """Turning autonomous off is the 'hold up' action — it must stop
        whatever's currently running immediately, not just flip a label."""
        mgr = SessionManager(sessions_dir)
        s = Session(mode="agent")

        class ForeverAgent:
            async def stream_async(self, prompt):
                while True:
                    await asyncio.sleep(10)
                    yield {}

        s._agent = ForeverAgent()
        mgr._sessions[s.id] = s
        s._task = asyncio.create_task(mgr._run_agent(s, s._agent, "go"))
        await asyncio.sleep(0.05)
        assert s.running

        await mgr.set_autonomous(s.id, False)

        assert not s.running
        assert s.mode == "assistant"
        assert s.id in mgr._sessions  # session survives, unlike stop()

    @pytest.mark.asyncio
    async def test_set_autonomous_off_when_idle_is_a_clean_noop_besides_the_mode_flip(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        s = Session(mode="agent")
        mgr._sessions[s.id] = s

        await mgr.set_autonomous(s.id, False)

        assert s.mode == "assistant"

    @pytest.mark.asyncio
    async def test_set_autonomous_on_without_a_task_does_not_send_a_resume_message(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        s = Session(mode="assistant", task_id=None)
        mgr._sessions[s.id] = s

        await mgr.set_autonomous(s.id, True)

        assert s.mode == "agent"
        assert s._task is None  # no send() was triggered

    @pytest.mark.asyncio
    async def test_set_autonomous_on_with_a_task_sends_a_resume_message(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        s = Session(mode="assistant", task_id="T-1")

        class QuickAgent:
            async def stream_async(self, prompt):
                return
                yield {}  # pragma: no cover — makes this an async generator

        s._agent = QuickAgent()
        mgr._sessions[s.id] = s

        await mgr.set_autonomous(s.id, True)
        await asyncio.sleep(0.05)

        assert s.mode == "agent"
        assert any(
            e.type == EventType.USER and "Resume working on the task" in e.message
            for e in s._history
        )

    def test_checkpoint_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            mgr.checkpoint("nonexistent", "before refactor")

    def test_revert_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            mgr.revert("nonexistent", "before refactor")

    def test_checkpoint_broadcasts_event(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        s = Session()
        mgr._sessions[s.id] = s
        q = s.subscribe()
        mgr.checkpoint(s.id, "before refactor")
        evt = q.get_nowait()
        assert evt.type == EventType.CHECKPOINT
        assert evt.message == "before refactor"

    def test_revert_broadcasts_state_change_not_a_real_revert(self, sessions_dir):
        """revert() is explicitly a no-op — it only logs the action."""
        mgr = SessionManager(sessions_dir)
        s = Session()
        mgr._sessions[s.id] = s
        q = s.subscribe()
        mgr.revert(s.id, "before refactor")
        evt = q.get_nowait()
        assert evt.type == EventType.STATE_CHANGE
        assert "not implemented" in evt.message

    @pytest.mark.asyncio
    async def test_interrupt_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            await mgr.interrupt("nonexistent")

    @pytest.mark.asyncio
    async def test_interrupt_noop_when_not_running(self, sessions_dir):
        """No task to cancel — should be a no-op, session stays put."""
        mgr = SessionManager(sessions_dir)
        s = Session()
        mgr._sessions[s.id] = s
        await mgr.interrupt(s.id)
        assert s.id in mgr._sessions

    @pytest.mark.asyncio
    async def test_interrupt_cancels_turn_but_keeps_session_alive(self, sessions_dir):
        """Regression guard for the 'stop kills the whole agent' complaint:
        interrupting a running turn must broadcast STATE_CHANGE (not
        ENDED) and leave the session in the manager, so a follow-up
        send() can continue the same conversation — unlike stop(), which
        tears the session down entirely."""
        mgr = SessionManager(sessions_dir)
        s = Session()

        class ForeverAgent:
            async def stream_async(self, prompt):
                while True:
                    await asyncio.sleep(10)
                    yield {}

        s._agent = ForeverAgent()
        mgr._sessions[s.id] = s
        s._task = asyncio.create_task(mgr._run_agent(s, s._agent, "go"))
        await asyncio.sleep(0.05)  # let the task actually start streaming
        assert s.running

        await mgr.interrupt(s.id)

        assert s.id in mgr._sessions
        assert not s.running
        assert s._history[-1].type == EventType.STATE_CHANGE
        assert "Cancelled" in s._history[-1].message
        assert not any(e.type == EventType.ENDED for e in s._history)


class TestSessionManagerStart:
    """Tests for SessionManager.start() — the core assembly path that had
    zero coverage. No task_description is passed in any of these, so the
    in-process runtime never actually runs the agent loop (no network
    calls); we're only testing that the session gets assembled correctly.
    """

    @pytest.mark.asyncio
    async def test_start_without_api_key_raises(self, sessions_dir, agent_knots_home):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(RuntimeError, match="No API key configured"):
            await mgr.start(model="fake/model", api_key="", base_url="http://fake")

    @pytest.mark.asyncio
    async def test_start_registers_session(self, sessions_dir, agent_knots_home):
        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            runtime_override="inprocess",
        )
        assert session.id in {s.id for s in mgr.active}
        assert session.mode == "agent"
        assert session._agent is not None
        assert session.model == "fake/model"
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_delegate_task_reaches_the_agent(self, sessions_dir, agent_knots_home):
        """Regression test: make_delegate_tool() used to be appended to the
        tool list *after* Agent(...) was already constructed, so the tool
        never actually reached the agent. Assert on the constructed
        Agent's own tool registry, not the intermediate list."""
        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            runtime_override="inprocess",
        )
        assert "delegate_task" in session._agent.tool_names
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_mark_criterion_met_tool_present(self, sessions_dir, agent_knots_home):
        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            runtime_override="inprocess",
        )
        assert "mark_criterion_met" in session._agent.tool_names
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_disabled_builtin_tool_excluded_from_agent(self, sessions_dir, agent_knots_home):
        """Regression test: ToolRegistry.list_builtin()/list_enabled() used
        to hardcode enabled=True and ignore the disabled-builtins file, so
        disabling a tool had no effect on what the agent actually got."""
        from agent_knots.tools.registry import ToolRegistry
        ToolRegistry().toggle_builtin("shell")

        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            runtime_override="inprocess",
        )
        assert "shell" not in session._agent.tool_names
        assert "editor" in session._agent.tool_names  # untouched tool still present
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_custom_tool_bound_to_session_workspace(self, sessions_dir, agent_knots_home, tmp_path):
        """Regression test: custom tools used to run subprocess.run() with
        no cwd at all, ignoring the session's workspace entirely."""
        from agent_knots.tools.registry import ToolRegistry, CustomTool

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ToolRegistry().add_custom(CustomTool(
            name="show_cwd", description="print cwd", command="pwd",
        ))

        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            working_dir=str(workspace),
            runtime_override="inprocess",
        )
        assert "show_cwd" in session._agent.tool_names
        tool_func = session._agent.tool_registry.registry["show_cwd"]._tool_func
        result = tool_func()
        assert result["stdout"].strip() == str(workspace)
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_start_with_no_task_description_does_not_run_agent(self, sessions_dir, agent_knots_home):
        """Without task_description, InProcessRuntime.start() shouldn't
        spawn the background agent task (which would make a real model
        call)."""
        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            runtime_override="inprocess",
        )
        assert session._task is None
        assert not session.running
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_start_with_task_id_but_no_prompt_still_runs(self, sessions_dir, agent_knots_home):
        """Regression: a session started via a bare 'Start' button on a
        task (no explicit prompt, task context baked into the system
        prompt instead) used to sit idle forever — 'agent' mode looked
        broken until the user manually intervened. task_id alone must be
        enough to kick off the first turn."""
        from agent_knots.config import tasks_dir
        from agent_knots.task.models import Task, new_task_id
        from agent_knots.task.store import TaskStore

        task = Task(id=new_task_id(), title="Do the thing")
        TaskStore(tasks_dir()).create(task)

        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            task_id=task.id, runtime_override="inprocess",
        )
        assert session._task is not None
        await mgr.stop(session.id)


@pytest.fixture
def git_repo(tmp_path):
    """A git repo with one commit on 'main'."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    git("add", "README.md")
    git("commit", "-qm", "initial")
    return repo


class TestSessionBranches:
    """Per-session git branches — see gitutil.ensure_session_branch."""

    @pytest.mark.asyncio
    async def test_creates_branch_for_a_repo_working_dir(self, sessions_dir, git_repo):
        from agent_knots.gitutil import current_branch

        mgr = SessionManager(sessions_dir)
        result = await mgr._ensure_branch(str(git_repo), None, "tsk-1", "sess1", False)

        assert result.skipped_reason is None
        assert result.name == "knots/tsk-1-sess1"
        assert result.created is True
        assert current_branch(git_repo) == "knots/tsk-1-sess1"

    @pytest.mark.asyncio
    async def test_skips_when_no_working_dir(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        result = await mgr._ensure_branch(None, None, "tsk-1", "sess1", False)

        assert result.name is None
        assert result.skipped_reason == "no working directory"

    @pytest.mark.asyncio
    async def test_skips_when_not_a_repo(self, sessions_dir, tmp_path):
        mgr = SessionManager(sessions_dir)
        result = await mgr._ensure_branch(str(tmp_path), None, "tsk-1", "sess1", False)

        assert result.name is None
        assert result.skipped_reason == "not a git repository"

    @pytest.mark.asyncio
    async def test_advisory_session_never_branches(self, sessions_dir, git_repo):
        """An advisory agent shares the writer's working tree, and git
        checkout is process-global — branching would move the writer's
        files too."""
        from agent_knots.gitutil import current_branch

        mgr = SessionManager(sessions_dir)
        result = await mgr._ensure_branch(str(git_repo), None, "tsk-1", "sess1", True)

        assert result.name is None
        assert "advisory" in result.skipped_reason
        assert current_branch(git_repo) == "main"

    @pytest.mark.asyncio
    async def test_second_writer_in_same_repo_skips(self, sessions_dir, git_repo):
        """Two writers would fight over HEAD; the second leaves the
        first's checkout alone."""
        mgr = SessionManager(sessions_dir)
        first = Session(id="sess1", working_dir=str(git_repo))
        mgr._sessions["sess1"] = first
        mgr._repo_writers[str(git_repo)] = "sess1"

        result = await mgr._ensure_branch(str(git_repo), None, "tsk-2", "sess2", False)

        assert result.name is None
        assert "already checked out by session sess1" in result.skipped_reason

    @pytest.mark.asyncio
    async def test_existing_branch_is_reused_not_recreated(self, sessions_dir, git_repo):
        mgr = SessionManager(sessions_dir)
        await mgr._ensure_branch(str(git_repo), None, "tsk-1", "sess1", False)
        mgr._repo_writers.clear()

        result = await mgr._ensure_branch(str(git_repo), None, "tsk-1", "sess1", False)

        assert result.created is False
        assert result.name == "knots/tsk-1-sess1"

    @pytest.mark.asyncio
    async def test_stop_deletes_branch_with_no_commits(self, sessions_dir, git_repo):
        from agent_knots.gitutil import branch_exists, current_branch

        mgr = SessionManager(sessions_dir)
        session = Session(
            id="sess1", working_dir=str(git_repo),
            branch="knots/tsk-1-sess1", branch_created=True, branch_base="main",
        )
        await mgr._ensure_branch(str(git_repo), None, "tsk-1", "sess1", False)
        mgr._sessions[session.id] = session

        await mgr.stop(session.id)

        assert branch_exists(git_repo, "knots/tsk-1-sess1") is False
        assert current_branch(git_repo) == "main"

    @pytest.mark.asyncio
    async def test_stop_keeps_branch_that_has_commits(self, sessions_dir, git_repo):
        import subprocess

        from agent_knots.gitutil import branch_exists

        mgr = SessionManager(sessions_dir)
        await mgr._ensure_branch(str(git_repo), None, "tsk-1", "sess1", False)
        (git_repo / "work.txt").write_text("real work\n")
        subprocess.run(["git", "add", "work.txt"], cwd=str(git_repo), check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", "work"], cwd=str(git_repo), check=True,
                       capture_output=True)

        session = Session(
            id="sess1", working_dir=str(git_repo),
            branch="knots/tsk-1-sess1", branch_created=True, branch_base="main",
        )
        mgr._sessions[session.id] = session
        await mgr.stop(session.id)

        assert branch_exists(git_repo, "knots/tsk-1-sess1") is True

    @pytest.mark.asyncio
    async def test_stop_releases_the_repo_for_the_next_writer(self, sessions_dir, git_repo):
        mgr = SessionManager(sessions_dir)
        session = Session(id="sess1", working_dir=str(git_repo))
        mgr._sessions[session.id] = session
        mgr._repo_writers[str(git_repo)] = "sess1"

        await mgr.stop(session.id)

        assert str(git_repo) not in mgr._repo_writers

    @pytest.mark.asyncio
    async def test_start_records_branch_on_the_session(
        self, sessions_dir, git_repo, agent_knots_home,
    ):
        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            working_dir=str(git_repo), runtime_override="inprocess",
        )

        assert session.branch == f"knots/session-{session.id}"
        assert session.branch_created is True
        assert session.branch_base == "main"
        assert mgr._repo_writers[str(git_repo)] == session.id
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_start_logs_the_branch_to_the_task(
        self, sessions_dir, git_repo, agent_knots_home,
    ):
        """The task YAML is the only durable record of which branch a
        session's work went to — sessions themselves are in-memory."""
        from agent_knots.config import tasks_dir
        from agent_knots.task.models import Task, new_task_id
        from agent_knots.task.store import TaskStore

        store = TaskStore(tasks_dir())
        task = store.create(Task(id=new_task_id(), title="Branch me"))

        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            task_id=task.id, working_dir=str(git_repo), runtime_override="inprocess",
        )

        entries = [p.entry for p in store.get(task.id).progress]
        assert any(session.branch in e for e in entries)
        await mgr.stop(session.id)


class TestVaultCredentialInjection:
    """A task's required_credentials should reach the shell tool as env
    vars, without the value ever landing in the system prompt or a tool
    result — see vault.store.resolve_env / sandbox_tools.scrub_secrets."""

    @pytest.mark.asyncio
    async def test_credential_reaches_the_shell_tool_scrubbed(
        self, sessions_dir, git_repo, agent_knots_home,
    ):
        from agent_knots.config import tasks_dir, vault_dir
        from agent_knots.task.models import Task, new_task_id
        from agent_knots.task.store import TaskStore
        from agent_knots.vault.store import Credential, InjectionTemplate, VaultStore

        vault = VaultStore(vault_dir())
        vault.unlock("passphrase")
        vault.add_credential(Credential(id="gh", value="supersecretvalue"))
        vault.set_template("gh", InjectionTemplate(name="e", env={"GH_TOKEN": "$value"}))

        task = TaskStore(tasks_dir()).create(Task(
            id=new_task_id(), title="Needs a credential", required_credentials=["gh"],
        ))

        mgr = SessionManager(sessions_dir, vault=vault)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            task_id=task.id, working_dir=str(git_repo), runtime_override="inprocess",
        )

        tool_func = session._agent.tool_registry.registry["shell_tool"]._tool_func
        result = tool_func(command="echo $GH_TOKEN")

        assert "supersecretvalue" not in result["stdout"]
        assert "[redacted:GH_TOKEN]" in result["stdout"]
        assert "supersecretvalue" not in session._agent.system_prompt
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_missing_credential_noted_in_system_prompt_not_raised(
        self, sessions_dir, git_repo, agent_knots_home,
    ):
        from agent_knots.config import tasks_dir, vault_dir
        from agent_knots.task.models import Task, new_task_id
        from agent_knots.task.store import TaskStore
        from agent_knots.vault.store import VaultStore

        vault = VaultStore(vault_dir())  # never unlocked

        task = TaskStore(tasks_dir()).create(Task(
            id=new_task_id(), title="Needs a credential", required_credentials=["gh"],
        ))

        mgr = SessionManager(sessions_dir, vault=vault)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            task_id=task.id, working_dir=str(git_repo), runtime_override="inprocess",
        )

        assert "Unavailable credentials" in session._agent.system_prompt
        assert "gh" in session._agent.system_prompt
        await mgr.stop(session.id)

    @pytest.mark.asyncio
    async def test_no_vault_configured_is_a_silent_noop(
        self, sessions_dir, git_repo, agent_knots_home,
    ):
        """SessionManager(vault=None) is the default every existing test
        and CLI vault command relies on — required_credentials must not
        crash a session that has no vault to resolve them from."""
        from agent_knots.config import tasks_dir
        from agent_knots.task.models import Task, new_task_id
        from agent_knots.task.store import TaskStore

        task = TaskStore(tasks_dir()).create(Task(
            id=new_task_id(), title="Needs a credential", required_credentials=["gh"],
        ))

        mgr = SessionManager(sessions_dir)
        session = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            task_id=task.id, working_dir=str(git_repo), runtime_override="inprocess",
        )

        assert "Unavailable credentials" not in session._agent.system_prompt
        await mgr.stop(session.id)
