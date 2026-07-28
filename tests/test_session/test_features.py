"""Tests for session/features.py — delegate_task/ask_user tool factories.

Previously zero coverage, which is exactly how a real bug shipped
silently: make_delegate_tool scheduled its sub-session start via
asyncio.create_task() from inside delegate_task, called only ever
directly (with a running loop already in scope) by any test that
existed — but Strands actually executes synchronous tool functions via
asyncio.to_thread, a worker thread with no running loop of its own.
create_task() there raises RuntimeError, silently swallowed, and no
sub-session was ever created. Only caught by testing against a real
model. These tests reproduce that same off-thread execution context.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from agent_knots.session.features import make_delegate_tool
from agent_knots.session.manager import SessionManager


@pytest.fixture
def sessions_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def agent_knots_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    from agent_knots.session.runtime import set_runtime_type
    set_runtime_type("inprocess")
    yield tmp_path


async def _wait_until(condition, timeout=2.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.02)
    return False


class TestDelegateTool:
    @pytest.mark.asyncio
    async def test_delegate_creates_a_sub_session_when_called_off_thread(
        self, sessions_dir, agent_knots_home, monkeypatch,
    ):
        """The realistic case: Strands calls the tool via asyncio.to_thread,
        not directly from a coroutine with its own running loop."""
        # The sub-session resolves its own provider config from scratch
        # (start() below passes it no model/api_key kwargs, same as the
        # real delegate_task) — needs env vars, not just the parent's
        # own explicit start() args.
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        mgr = SessionManager(sessions_dir)
        parent = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            runtime_override="inprocess",
        )

        delegate_tool = make_delegate_tool(mgr, parent.id)
        tool_func = delegate_tool._tool_func if hasattr(delegate_tool, "_tool_func") else delegate_tool

        result = await asyncio.to_thread(
            tool_func, title="Sub-task", description="Do a small thing",
        )
        assert "task_id" in result

        before = {parent.id}
        created = await _wait_until(
            lambda: any(s.id not in before for s in mgr.active),
        )
        assert created, "delegate_task must actually create a sub-session, even when called off-thread"

        sub_sessions = [s for s in mgr.active if s.id != parent.id]
        assert len(sub_sessions) == 1
        assert sub_sessions[0].task_id == result["task_id"]

        for s in list(mgr.active):
            await mgr.stop(s.id)

    @pytest.mark.asyncio
    async def test_delegate_broadcasts_a_delegate_event_to_the_parent(
        self, sessions_dir, agent_knots_home, monkeypatch,
    ):
        from agent_knots.events import EventType

        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        mgr = SessionManager(sessions_dir)
        parent = await mgr.start(
            model="fake/model", api_key="fake-key", base_url="http://fake",
            runtime_override="inprocess",
        )
        q = parent.subscribe()

        delegate_tool = make_delegate_tool(mgr, parent.id)
        tool_func = delegate_tool._tool_func if hasattr(delegate_tool, "_tool_func") else delegate_tool
        await asyncio.to_thread(tool_func, title="Sub-task 2")

        found = False
        for _ in range(50):
            try:
                evt = q.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.02)
                continue
            if evt.type == EventType.DELEGATE:
                found = True
                break
        assert found, "parent session must see a DELEGATE event once the sub-session starts"

        for s in list(mgr.active):
            await mgr.stop(s.id)
