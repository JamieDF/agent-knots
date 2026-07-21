"""Tests for the web cockpit server."""

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_knots.cockpit.web.server import create_app
from agent_knots.events import Event, EventType, ToolCall, serialize_event
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


class TestTaskAPI:
    @pytest.mark.asyncio
    async def test_create_task_default_review_gate(self, authed_client):
        resp = await authed_client.post("/api/tasks", json={"title": "Test task"})
        assert resp.status_code == 200
        assert resp.json()["review_gate"] == "manual"

    @pytest.mark.asyncio
    async def test_create_task_explicit_review_gate(self, authed_client):
        resp = await authed_client.post(
            "/api/tasks", json={"title": "Test task", "review_gate": "auto"}
        )
        assert resp.json()["review_gate"] == "auto"

    @pytest.mark.asyncio
    async def test_patch_updates_description_tags_criteria_steps(self, authed_client):
        """Regression: UpdateTaskRequest used to be missing these fields
        entirely, so PATCH silently dropped description/tags/criteria/
        steps edits sent by the frontend."""
        created = await authed_client.post("/api/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={
            "description": "new description",
            "tags": ["a", "b"],
            "acceptance_criteria": ["criterion one"],
            "steps": ["step one"],
            "review_gate": "none",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["description"] == "new description"
        assert body["tags"] == ["a", "b"]
        assert body["acceptance_criteria"] == ["criterion one"]
        assert [s["title"] for s in body["steps"]] == ["step one"]
        assert body["review_gate"] == "none"

    @pytest.mark.asyncio
    async def test_patch_preserves_criteria_met_for_unchanged_criteria(self, authed_client):
        """c1's met state must survive a PATCH that edits the criteria
        list but still includes c1 — proven by the done-gate: marking
        the task done should fail (c2 still unmet) rather than silently
        succeeding because the whole criteria_met list got wiped."""
        created = await authed_client.post("/api/tasks", json={
            "title": "T", "acceptance_criteria": ["c1", "c2"],
        })
        task_id = created.json()["id"]
        await authed_client.post(f"/api/tasks/{task_id}/criteria/toggle", json={
            "criterion": "c1", "met": True,
        })

        # Edit the criteria list (still includes c1 and c2) via PATCH.
        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={
            "acceptance_criteria": ["c1", "c2"],
        })
        assert resp.status_code == 200

        # c2 is still unmet, so done should be refused — the route doesn't
        # catch TaskStore's ValueError, so it propagates (matching this
        # server's existing behavior for the done-gate elsewhere).
        with pytest.raises(ValueError, match="unmet acceptance criteria"):
            await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "done"})

        # Mark c2 too — now done should succeed, proving c1's earlier
        # met state was never lost.
        await authed_client.post(f"/api/tasks/{task_id}/criteria/toggle", json={
            "criterion": "c2", "met": True,
        })
        done2 = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        assert done2.status_code == 200

    @pytest.mark.asyncio
    async def test_patch_preserves_step_status_for_unchanged_steps(self, authed_client):
        created = await authed_client.post("/api/tasks", json={"title": "T"})
        task_id = created.json()["id"]
        await authed_client.patch(f"/api/tasks/{task_id}", json={"steps": ["step a"]})

        # Editing the step list again (same title) should reuse the same
        # step id/status rather than creating a fresh draft step.
        first = (await authed_client.get(f"/api/tasks/{task_id}")).json()
        step_id = first["steps"][0]["id"]

        await authed_client.patch(f"/api/tasks/{task_id}", json={"steps": ["step a", "step b"]})
        second = (await authed_client.get(f"/api/tasks/{task_id}")).json()
        assert second["steps"][0]["id"] == step_id

    @pytest.mark.asyncio
    async def test_criteria_toggle_mark_and_unmark(self, authed_client):
        created = await authed_client.post("/api/tasks", json={
            "title": "T", "acceptance_criteria": ["only criterion"],
        })
        task_id = created.json()["id"]

        marked = await authed_client.post(f"/api/tasks/{task_id}/criteria/toggle", json={
            "criterion": "only criterion", "met": True,
        })
        assert marked.status_code == 200

        # Now DONE transition should succeed since the sole criterion is met.
        done = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        assert done.status_code == 200
        assert done.json()["status"] == "done"

    @pytest.mark.asyncio
    async def test_task_response_includes_criteria_met(self, authed_client):
        """Regression: _task_to_response() used to omit criteria_met
        entirely, so the frontend had no way to know which criteria were
        already met on page load (only which ones exist)."""
        created = await authed_client.post("/api/tasks", json={
            "title": "T", "acceptance_criteria": ["c1", "c2"],
        })
        task_id = created.json()["id"]
        assert created.json()["criteria_met"] == []

        await authed_client.post(f"/api/tasks/{task_id}/criteria/toggle", json={
            "criterion": "c1", "met": True,
        })
        detail = await authed_client.get(f"/api/tasks/{task_id}")
        assert detail.json()["criteria_met"] == ["c1"]

    @pytest.mark.asyncio
    async def test_criteria_toggle_unknown_task_404s(self, authed_client):
        resp = await authed_client.post("/api/tasks/nonexistent/criteria/toggle", json={
            "criterion": "x", "met": True,
        })
        assert resp.status_code == 404


class TestAgentDetailAPI:
    @pytest.mark.asyncio
    async def test_get_unknown_agent_404s(self, authed_client):
        resp = await authed_client.get("/api/agent/nonexistent")
        assert resp.status_code == 404


class TestDraftTaskAPI:
    @pytest.mark.asyncio
    async def test_draft_blocked_when_unconfigured(self, authed_client):
        resp = await authed_client.post("/api/tasks/draft", json={"title": "Add dark mode"})
        assert resp.status_code == 400


class TestSPAFallback:
    @pytest.mark.asyncio
    async def test_unknown_path_serves_spa_shell(self, authed_client):
        """BrowserRouter paths like /tasks/T-123 must serve the SPA shell
        on a hard refresh, not 404."""
        resp = await authed_client.get("/tasks/T-123")
        assert resp.status_code == 200
        assert "agent-knots cockpit" in resp.text

    @pytest.mark.asyncio
    async def test_unknown_api_path_still_404s(self, authed_client):
        """The catch-all must not shadow /api/* — it's registered last,
        but still needs its own belt-and-suspenders check."""
        resp = await authed_client.get("/api/nonexistent")
        assert resp.status_code == 404


class TestEventSerialization:
    """serialize_event() is the JSON wire format that replaced
    format_event_html() — the frontend now owns all rendering, so this
    just needs to be a faithful, JSON-safe mirror of the Event dataclass."""

    def test_message_event(self):
        evt = Event(type=EventType.MESSAGE, session_id="s", message="hello")
        d = serialize_event(evt)
        assert d["type"] == "message"
        assert d["session_id"] == "s"
        assert d["message"] == "hello"

    def test_tool_call_event_nested_dataclass(self):
        evt = Event(
            type=EventType.TOOL_CALL,
            session_id="s",
            tool_call=ToolCall(id="1", name="bash", args={"command": "ls"}),
        )
        d = serialize_event(evt)
        assert d["type"] == "tool_call"
        assert d["tool_call"] == {"id": "1", "name": "bash", "args": {"command": "ls"}}

    def test_error_event(self):
        evt = Event(type=EventType.ERROR, session_id="s", error="something broke")
        d = serialize_event(evt)
        assert d["type"] == "error"
        assert d["error"] == "something broke"

    def test_new_event_types_serialize(self):
        for et in (EventType.AUTO_LOG, EventType.STEER, EventType.DELEGATE,
                   EventType.CHECKPOINT, EventType.USER, EventType.ENDED):
            evt = Event(type=et, session_id="s", message="x")
            assert serialize_event(evt)["type"] == et.value

    def test_json_serializable(self):
        """The whole point: this must survive json.dumps for the SSE wire."""
        import json
        evt = Event(
            type=EventType.DELEGATE,
            session_id="s",
            data={"sub_session_id": "abc", "sub_task_id": "T-1"},
        )
        json.dumps(serialize_event(evt))  # should not raise
