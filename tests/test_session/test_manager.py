"""Tests for SessionManager and Session."""

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

        # Second fragment carries the closing tag partway through — still
        # thinking content up to the tag, tag itself stripped.
        full = "<think>\nThe user wants to know X.\n</think>\n\n"
        evt2 = SessionManager._chunk_to_event("sid", {
            "data": full, "delta": {"text": full},
        }, state)
        assert evt2.type == EventType.THINKING
        assert "</think>" not in evt2.message
        assert "wants to know X" in evt2.message

        # A subsequent fragment with no tags at all is back to MESSAGE.
        full2 = full + "The answer is 4."
        evt3 = SessionManager._chunk_to_event("sid", {
            "data": full2, "delta": {"text": full2},
        }, state)
        assert evt3.type == EventType.MESSAGE
        assert evt3.message == "The answer is 4."

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

    def test_result_chunk(self):
        """Real Strands chunk: result."""
        evt = SessionManager._chunk_to_event("sid", {
            "result": "AgentResult(...)",
        })
        assert evt is not None
        assert evt.type == EventType.STATE_CHANGE

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
    async def test_send_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            await mgr.send("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_set_mode_nonexistent(self, sessions_dir):
        mgr = SessionManager(sessions_dir)
        with pytest.raises(ValueError, match="not found"):
            await mgr.set_mode("nonexistent", "assistant")

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
