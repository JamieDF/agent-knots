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
    async def test_event_stream_is_async_queue(self):
        s = Session()
        assert isinstance(s._events, asyncio.Queue)
        await s._events.put(Event(type=EventType.MESSAGE, session_id=s.id, message="hi"))
        evt = await s._events.get()
        assert evt.message == "hi"


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
