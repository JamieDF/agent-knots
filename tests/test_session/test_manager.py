"""Tests for SessionManager and Session."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from agentjam.events import Event, EventType, ToolCall
from agentjam.session.manager import Session, SessionManager


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
    def test_string_chunk(self):
        evt = SessionManager._chunk_to_event("sid", "hello")
        assert evt is not None
        assert evt.type == EventType.MESSAGE
        assert evt.message == "hello"
        assert evt.session_id == "sid"

    def test_thinking_chunk(self):
        evt = SessionManager._chunk_to_event("sid", {"type": "thinking", "content": "hmm..."})
        assert evt is not None
        assert evt.type == EventType.THINKING
        assert evt.message == "hmm..."

    def test_tool_call_chunk(self):
        evt = SessionManager._chunk_to_event("sid", {
            "type": "tool_call",
            "id": "tc1",
            "name": "bash",
            "args": {"command": "ls -la"},
        })
        assert evt is not None
        assert evt.type == EventType.TOOL_CALL
        assert evt.tool_call is not None
        assert evt.tool_call.name == "bash"
        assert evt.tool_call.args == {"command": "ls -la"}

    def test_tool_result_chunk(self):
        evt = SessionManager._chunk_to_event("sid", {
            "type": "tool_result",
            "output": "file1.txt\nfile2.txt",
        })
        assert evt is not None
        assert evt.type == EventType.TOOL_RESULT
        assert evt.message == "file1.txt\nfile2.txt"

    def test_none_chunk(self):
        assert SessionManager._chunk_to_event("sid", None) is None

    def test_unknown_dict_chunk(self):
        """Unknown dict types become MESSAGE events."""
        evt = SessionManager._chunk_to_event("sid", {"something": "else"})
        assert evt is not None
        assert evt.type == EventType.MESSAGE

    def test_tool_call_without_id(self):
        evt = SessionManager._chunk_to_event("sid", {
            "type": "tool_call",
            "name": "read",
        })
        assert evt is not None
        assert evt.tool_call is not None
        assert evt.tool_call.id == ""


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
