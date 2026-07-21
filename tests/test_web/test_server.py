"""Tests for the web cockpit server."""

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_knots.cockpit.web.server import create_app, format_event_html
from agent_knots.events import Event, EventType, ToolCall
from agent_knots.session.manager import SessionManager


@pytest.fixture
def agent_knots_home(tmp_path, monkeypatch):
    """Isolate AGENT_KNOTS_HOME so tests never read/write the real user's
    cockpit token file."""
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def auth_token(agent_knots_home):
    """The token the app under test will authenticate against.
    load_or_create_token is idempotent, so it doesn't matter whether this
    or create_app()'s own Auth(...) call creates the file first — both
    read/write the same path and agree on the same value."""
    from agent_knots.config import cockpit_token_file
    from agent_knots.cockpit.web.auth import load_or_create_token
    return load_or_create_token(cockpit_token_file())


@pytest.fixture
def session_manager(agent_knots_home):
    with tempfile.TemporaryDirectory() as d:
        yield SessionManager(Path(d))


@pytest.fixture
async def client(session_manager):
    app = create_app(session_manager)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        yield c


@pytest.fixture
async def raw_client(session_manager):
    """Same as `client` but without auto-following redirects, so tests can
    assert on the redirect itself (status code, Location header)."""
    app = create_app(session_manager)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as c:
        yield c


@pytest.fixture
async def authed_client(client, auth_token):
    """A `client` that's already logged in, for tests that don't care
    about auth itself and just need past it."""
    client.cookies.set("agent-knots-session", auth_token)
    return client


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
        assert "agent-knots cockpit" in resp.text

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

    @pytest.mark.asyncio
    async def test_query_token_grants_access(self, client, auth_token):
        resp = await client.get(f"/api/agents?token={auth_token}")
        assert resp.status_code == 200
        assert resp.json() == {"agents": []}

    @pytest.mark.asyncio
    async def test_wrong_query_token_denied(self, client, auth_token):
        resp = await client.get("/api/agents?token=not-the-real-token")
        assert "Enter your access token" in resp.text

    @pytest.mark.asyncio
    async def test_cookie_grants_access(self, raw_client, auth_token):
        raw_client.cookies.set("agent-knots-session", auth_token)
        resp = await raw_client.get("/api/agents")
        assert resp.status_code == 200
        assert resp.json() == {"agents": []}

    @pytest.mark.asyncio
    async def test_wrong_cookie_denied(self, raw_client):
        raw_client.cookies.set("agent-knots-session", "not-the-real-token")
        resp = await raw_client.get("/api/agents")
        assert resp.status_code == 303  # redirect to login

    @pytest.mark.asyncio
    async def test_bearer_token_grants_access(self, raw_client, auth_token):
        resp = await raw_client.get(
            "/api/agents", headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"agents": []}

    @pytest.mark.asyncio
    async def test_wrong_bearer_token_denied(self, raw_client):
        resp = await raw_client.get(
            "/api/agents", headers={"Authorization": "Bearer not-the-real-token"}
        )
        assert resp.status_code == 303

    @pytest.mark.asyncio
    async def test_login_post_wrong_token_shows_error(self, client, auth_token):
        resp = await client.post("/login", data={"token": "wrong", "return_url": "/"})
        assert "Invalid token" in resp.text

    @pytest.mark.asyncio
    async def test_login_post_correct_token_sets_cookie_and_redirects(self, raw_client, auth_token):
        resp = await raw_client.post(
            "/login", data={"token": auth_token, "return_url": "/api/agents"},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/api/agents"
        assert "agent-knots-session" in resp.cookies

        # The cookie actually works on a follow-up request.
        resp2 = await raw_client.get("/api/agents")
        assert resp2.status_code == 200


class TestSettingsAPI:
    """"configured" must reflect resolve_provider()'s full precedence
    (env vars included), not just the settings file — otherwise a GUI
    user who configured via AGENT_KNOTS_API_KEY gets stuck behind the
    setup wizard, and POST /api/sessions refuses to start a session that
    would actually have worked."""

    @pytest.mark.asyncio
    async def test_not_configured_by_default(self, authed_client):
        resp = await authed_client.get("/api/settings")
        assert resp.json()["configured"] is False

    @pytest.mark.asyncio
    async def test_configured_via_settings_file(self, authed_client):
        await authed_client.put("/api/settings", json={
            "default_model": "openai/gpt-4o-mini", "api_key": "sk-test",
        })
        resp = await authed_client.get("/api/settings")
        assert resp.json()["configured"] is True

    @pytest.mark.asyncio
    async def test_configured_via_env_var_without_settings_file(self, authed_client, monkeypatch):
        """Regression: this used to only check the settings file, so an
        env-var-only setup (common for containers/CI) left the GUI
        thinking it wasn't configured at all."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-from-env")
        resp = await authed_client.get("/api/settings")
        assert resp.json()["configured"] is True

    @pytest.mark.asyncio
    async def test_create_session_blocked_when_unconfigured(self, authed_client):
        resp = await authed_client.post("/api/sessions", json={"prompt": "hi"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_session_not_blocked_by_configured_check_via_env(self, authed_client, monkeypatch):
        """Regression: POST /api/sessions used to refuse to even try
        starting a session if the settings *file* had no api_key, even
        when env vars would have made SessionManager.start() succeed."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-from-env")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake")
        resp = await authed_client.post("/api/sessions", json={"prompt": ""})
        # No prompt means no background agent task is spawned (no network
        # call) — we only care that the pre-flight "not configured" 400
        # didn't fire; a real 200 here confirms the check passed.
        assert resp.status_code != 400


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
