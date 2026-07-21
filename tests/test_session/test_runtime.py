"""Tests for session/runtime.py — InProcessRuntime, SubprocessRuntime
selection, and create_runtime()'s type resolution.

Previously had zero coverage; this is where two real bugs lived:
InProcessRuntime.start() was a no-op, and create_runtime() only ever
consulted the global runtime-type setting, ignoring an explicitly
resolved type passed in by the caller.
"""

import asyncio

import pytest

from agent_knots.session.manager import Session
from agent_knots.session.runtime import (
    InProcessRuntime,
    SubprocessRuntime,
    create_runtime,
    get_runtime_type,
    set_runtime_type,
)


@pytest.fixture(autouse=True)
def reset_runtime_type():
    """Global runtime-type state — reset around every test so tests can't
    leak into each other."""
    original = get_runtime_type()
    yield
    set_runtime_type(original)


class FakeManager:
    """Minimal stand-in for SessionManager — just enough for
    InProcessRuntime to delegate to."""

    def __init__(self):
        self.ran_with = None
        self.sent = []
        self.modes_set = []

    async def _run_agent(self, session, agent, prompt):
        self.ran_with = (session.id, agent, prompt)

    async def send(self, session_id, message):
        self.sent.append((session_id, message))

    async def set_mode(self, session_id, mode):
        self.modes_set.append((session_id, mode))


class TestCreateRuntime:
    def test_default_type_is_inprocess(self):
        set_runtime_type("inprocess")
        assert isinstance(create_runtime(), InProcessRuntime)

    def test_global_subprocess_setting(self):
        set_runtime_type("subprocess")
        assert isinstance(create_runtime(), SubprocessRuntime)

    def test_explicit_type_overrides_global_to_subprocess(self):
        """Regression: an explicitly resolved runtime_type (e.g. a
        per-project override) must win over a stale global default."""
        set_runtime_type("inprocess")
        assert isinstance(create_runtime(runtime_type="subprocess"), SubprocessRuntime)

    def test_explicit_type_overrides_global_to_inprocess(self):
        set_runtime_type("subprocess")
        assert isinstance(create_runtime(runtime_type="inprocess"), InProcessRuntime)

    def test_inprocess_runtime_carries_session_manager(self):
        mgr = FakeManager()
        runtime = create_runtime(mgr, runtime_type="inprocess")
        assert runtime._mgr is mgr


class TestInProcessRuntime:
    @pytest.mark.asyncio
    async def test_start_with_task_description_creates_task(self):
        """Regression: start() used to be a bare `pass` — the agent never
        actually ran in-process despite SessionRuntime claiming to own
        that responsibility."""
        mgr = FakeManager()
        runtime = InProcessRuntime(mgr)
        session = Session(_agent=object())

        await runtime.start(session, {"task_description": "do the thing"})

        assert session._task is not None
        await session._task  # let it run to completion
        assert mgr.ran_with == (session.id, session._agent, "do the thing")

    @pytest.mark.asyncio
    async def test_start_without_task_description_does_nothing(self):
        mgr = FakeManager()
        runtime = InProcessRuntime(mgr)
        session = Session(_agent=object())

        await runtime.start(session, {"task_description": ""})

        assert session._task is None

    @pytest.mark.asyncio
    async def test_start_without_agent_does_nothing(self):
        mgr = FakeManager()
        runtime = InProcessRuntime(mgr)
        session = Session(_agent=None)

        await runtime.start(session, {"task_description": "do the thing"})

        assert session._task is None

    @pytest.mark.asyncio
    async def test_send_delegates_to_manager(self):
        mgr = FakeManager()
        runtime = InProcessRuntime(mgr)
        session = Session()

        await runtime.send(session, "hello")

        assert mgr.sent == [(session.id, "hello")]

    @pytest.mark.asyncio
    async def test_set_mode_delegates_to_manager(self):
        mgr = FakeManager()
        runtime = InProcessRuntime(mgr)
        session = Session()

        await runtime.set_mode(session, "assistant")

        assert mgr.modes_set == [(session.id, "assistant")]

    @pytest.mark.asyncio
    async def test_stop_cancels_session(self):
        mgr = FakeManager()
        runtime = InProcessRuntime(mgr)
        session = Session()

        async def never_finishes():
            await asyncio.sleep(100)

        session._task = asyncio.create_task(never_finishes())
        await runtime.stop(session)

        assert session._task.cancelled() or session._task.done()
