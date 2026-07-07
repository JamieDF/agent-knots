"""Tests for the web cockpit server."""

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentjam.cockpit.web.server import create_app, format_event_html
from agentjam.events import Event, EventType, ToolCall
from agentjam.session.manager import SessionManager


@pytest.fixture
def session_manager():
    with tempfile.TemporaryDirectory() as d:
        yield SessionManager(Path(d))


@pytest.fixture
async def client(session_manager):
    app = create_app(session_manager)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        yield c


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agents"] == 0


class TestAgentsAPI:
    @pytest.mark.asyncio
    async def test_list_empty_redirects_to_login(self, client):
        """Without auth, /api/agents redirects to login page."""
        resp = await client.get("/api/agents")
        assert resp.status_code == 200  # follows redirect to login page
        assert "Enter your access token" in resp.text


class TestAuth:
    @pytest.mark.asyncio
    async def test_login_page(self, client):
        resp = await client.get("/login")
        assert resp.status_code == 200
        assert "agentjam cockpit" in resp.text

    @pytest.mark.asyncio
    async def test_protected_redirects_to_login(self, client):
        """Protected routes redirect to the login page."""
        resp = await client.get("/")
        # With follow_redirects=True, ends up at login page
        assert resp.status_code == 200
        assert "Enter your access token" in resp.text

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, client):
        """Health endpoint is public — no auth needed."""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestEventFormatting:
    def test_message_event(self):
        evt = Event(type=EventType.MESSAGE, session_id="s", message="hello")
        html = format_event_html(evt)
        assert "hello" in html
        assert 'prose-avatar agent' in html

    def test_thinking_event(self):
        evt = Event(type=EventType.THINKING, session_id="s", message="hmm")
        html = format_event_html(evt)
        assert "hmm" in html
        assert "prose-thinking" in html

    def test_tool_call_event(self):
        evt = Event(
            type=EventType.TOOL_CALL,
            session_id="s",
            tool_call=ToolCall(id="1", name="bash", args={"command": "ls"}),
        )
        html = format_event_html(evt)
        assert "bash" in html
        assert "tool-card" in html

    def test_error_event(self):
        evt = Event(type=EventType.ERROR, session_id="s", error="something broke")
        html = format_event_html(evt)
        assert "something broke" in html
        assert "prose-error" in html

    def test_blocker_event(self):
        evt = Event(type=EventType.BLOCKER, session_id="s", message="Approve?")
        html = format_event_html(evt)
        assert "Approve?" in html
        assert "prose-blocker" in html

    def test_state_change_event(self):
        evt = Event(type=EventType.STATE_CHANGE, session_id="s", message="Mode changed")
        html = format_event_html(evt)
        assert "Mode changed" in html
        assert "prose-state" in html

    def test_html_escaping(self):
        evt = Event(type=EventType.MESSAGE, session_id="s", message='<script>alert("xss")</script>')
        html = format_event_html(evt)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
