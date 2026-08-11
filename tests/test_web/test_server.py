"""Tests for the web cockpit server."""

import asyncio
import subprocess
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
        assert "Access token" in resp.text


class TestAuth:
    @pytest.mark.asyncio
    async def test_login_page(self, client):
        resp = await client.get("/login")
        assert resp.status_code == 200
        assert "agent-knots" in resp.text

    @pytest.mark.asyncio
    async def test_protected_redirects_to_login(self, client):
        """Protected routes redirect to the login page."""
        resp = await client.get("/")
        # With follow_redirects=True, ends up at login page
        assert resp.status_code == 200
        assert "Access token" in resp.text

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
        assert "Access token" in resp.text

    @pytest.mark.asyncio
    async def test_root_with_query_token_logs_in_directly(self, raw_client, auth_token):
        """The printed "one-click" cockpit URL is http://host:port/?token=...
        — opening it in a browser must log in directly instead of bouncing
        to the login page asking for the token to be pasted in (a real bug:
        the query-token check used to be scoped to /api/* paths only, so
        the root path fell through to requiring a cookie that didn't exist
        yet)."""
        resp = await raw_client.get(f"/?token={auth_token}")
        assert resp.status_code == 303
        assert resp.cookies["agent-knots-session"] == auth_token
        # Redirects to a clean URL — token stripped, not left in the address bar.
        assert resp.headers["location"] == "/"

    @pytest.mark.asyncio
    async def test_root_with_query_token_end_to_end(self, client, auth_token):
        """Following the redirect (like a real browser) lands on the actual
        SPA shell, not the login page."""
        resp = await client.get(f"/?token={auth_token}")
        assert resp.status_code == 200
        assert "Access token" not in resp.text

    @pytest.mark.asyncio
    async def test_deep_link_with_query_token_preserves_path_and_strips_token(self, raw_client, auth_token):
        resp = await raw_client.get(f"/agent/abc123?token={auth_token}&foo=bar")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/agent/abc123?foo=bar"

    @pytest.mark.asyncio
    async def test_wrong_query_token_on_root_denied(self, raw_client):
        resp = await raw_client.get("/?token=not-the-real-token")
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/login")

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
    async def test_wastebin_retention_defaults_to_30_days(self, authed_client):
        resp = await authed_client.get("/api/settings")
        assert resp.json()["wastebin"]["retention_days"] == 30

    @pytest.mark.asyncio
    async def test_wastebin_retention_round_trips(self, authed_client):
        await authed_client.put("/api/settings", json={"wastebin_retention_days": 7})
        resp = await authed_client.get("/api/settings")
        assert resp.json()["wastebin"]["retention_days"] == 7

    @pytest.mark.asyncio
    async def test_wastebin_retention_zero_is_a_real_value_not_ignored(self, authed_client):
        """0 means 'never auto-purge' — a meaningful setting, not the
        empty-string-means-preserve convention the string fields use."""
        await authed_client.put("/api/settings", json={"wastebin_retention_days": 7})
        await authed_client.put("/api/settings", json={"wastebin_retention_days": 0})
        resp = await authed_client.get("/api/settings")
        assert resp.json()["wastebin"]["retention_days"] == 0

    @pytest.mark.asyncio
    async def test_wastebin_retention_omitted_preserves_existing(self, authed_client):
        await authed_client.put("/api/settings", json={"wastebin_retention_days": 14})
        await authed_client.put("/api/settings", json={"default_model": "gpt-4o"})
        resp = await authed_client.get("/api/settings")
        assert resp.json()["wastebin"]["retention_days"] == 14

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

    @pytest.mark.asyncio
    async def test_create_session_actually_uses_env_model_not_settings_file(self, authed_client, monkeypatch):
        """Regression: create_session() used to pass settings.load()'s
        default_model/api_key/base_url straight through to
        SessionManager.start(), which always outranks env vars in
        resolve_provider()'s precedence — silently ignoring env-var-only
        configuration for the actual session, even though the
        "configured" pre-flight check above already resolved env vars
        correctly. A session started with only env vars set (no api_key
        ever saved to the settings file) must build its agent against
        the env-configured model, not the file's default."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-from-env")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model-from-env")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake")
        resp = await authed_client.post("/api/sessions", json={"prompt": ""})
        assert resp.status_code == 200
        agent_id = resp.json()["id"]

        detail = await authed_client.get(f"/api/agent/{agent_id}")
        assert detail.json()["model"] == "fake/model-from-env"


class TestTaskAPI:
    @pytest.mark.asyncio
    async def test_create_task_default_review_gate(self, authed_client):
        resp = await authed_client.post("/api/tasks", json={"title": "Test task"})
        assert resp.status_code == 200
        assert resp.json()["review_gate"] == "manual"

    @pytest.mark.asyncio
    async def test_create_task_defaults_to_draft_status(self, authed_client):
        """New tasks start in Draft, not Open — they move to Open only
        once someone deliberately takes them out of draft."""
        resp = await authed_client.post("/api/tasks", json={"title": "Test task"})
        assert resp.json()["status"] == "draft"

    @pytest.mark.asyncio
    async def test_cannot_skip_review_straight_to_done_via_patch(self, authed_client):
        """Workflow protocol: a task with review_gate != 'none' can't jump
        straight from in_progress to done, even with no acceptance
        criteria at all — it must pass through 'review' first."""
        created = await authed_client.post("/api/tasks", json={"title": "No criteria task"})
        task_id = created.json()["id"]
        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})

        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        assert resp.status_code == 400
        assert "review" in resp.json()["detail"]

        # Passing through review first should succeed.
        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "review"})
        resp2 = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_patch_updates_dependencies(self, authed_client):
        blocker = await authed_client.post("/api/tasks", json={"title": "Blocker"})
        blocker_id = blocker.json()["id"]
        task = await authed_client.post("/api/tasks", json={"title": "Blocked"})
        task_id = task.json()["id"]

        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={"dependencies": [blocker_id]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["dependencies"] == [blocker_id]
        assert body["unmet_dependencies"] == [{"id": blocker_id, "title": "Blocker"}]

    @pytest.mark.asyncio
    async def test_task_cannot_depend_on_itself(self, authed_client):
        task = await authed_client.post("/api/tasks", json={"title": "T"})
        task_id = task.json()["id"]
        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={"dependencies": [task_id]})
        assert resp.json()["dependencies"] == []

    @pytest.mark.asyncio
    async def test_unmet_dependencies_clears_once_blocker_done(self, authed_client):
        blocker = await authed_client.post("/api/tasks", json={"title": "Blocker", "review_gate": "none"})
        blocker_id = blocker.json()["id"]
        await authed_client.patch(f"/api/tasks/{blocker_id}", json={"status": "in_progress"})
        await authed_client.patch(f"/api/tasks/{blocker_id}", json={"status": "done"})

        task = await authed_client.post("/api/tasks", json={"title": "Blocked", "dependencies": [blocker_id]})
        assert task.json()["unmet_dependencies"] == []

    @pytest.mark.asyncio
    async def test_create_task_explicit_review_gate(self, authed_client):
        resp = await authed_client.post(
            "/api/tasks", json={"title": "Test task", "review_gate": "auto"}
        )
        assert resp.json()["review_gate"] == "auto"

    @pytest.mark.asyncio
    async def test_patch_title_and_assign_together_both_persist(self, authed_client):
        """Regression guard for a redundant-writes cleanup: update_task()
        now batches the plain content fields (title, description, tags,
        etc.) into a single store.update() instead of one write per
        field, but TaskStore.assign() re-fetches the task from disk
        itself rather than taking the in-memory object — so if the batch
        write isn't flushed before assign() runs, assign's fresh
        re-fetch would silently lose whatever the batch write hadn't
        persisted yet. Both must survive in the same PATCH."""
        created = await authed_client.post("/api/tasks", json={"title": "Old title"})
        task_id = created.json()["id"]

        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={
            "title": "New title", "assign": "agent-42",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "New title"
        assert body["assigned_to"] == "agent-42"

        # Re-fetch independently to prove it's really on disk, not just
        # in the response from the same request.
        refetched = await authed_client.get(f"/api/tasks/{task_id}")
        assert refetched.json()["title"] == "New title"
        assert refetched.json()["assigned_to"] == "agent-42"

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

        # c2 is still unmet, so done should be refused with a clean 400.
        refused = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        assert refused.status_code == 400
        assert "unmet acceptance criteria" in refused.json()["detail"]

        # Mark c2 too — now done should succeed, proving c1's earlier
        # met state was never lost.
        await authed_client.post(f"/api/tasks/{task_id}/criteria/toggle", json={
            "criterion": "c2", "met": True,
        })
        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "review"})
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

        # Now DONE transition should succeed since the sole criterion is met
        # and the task has passed through review.
        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "review"})
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


class TestTaskDependencyGate:
    """Ticket dependencies: task A can declare it depends on task B, and
    can't be started (moved to in_progress) until B is done."""

    @pytest.mark.asyncio
    async def test_create_session_refuses_when_task_blocked(self, authed_client, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-from-env")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake")

        blocker = await authed_client.post("/api/tasks", json={"title": "Blocker"})
        blocker_id = blocker.json()["id"]
        blocked = await authed_client.post("/api/tasks", json={
            "title": "Blocked", "status": "open", "dependencies": [blocker_id],
        })
        blocked_id = blocked.json()["id"]

        resp = await authed_client.post("/api/sessions", json={"prompt": "", "task_id": blocked_id})
        assert resp.status_code == 400
        assert "blocked by unfinished dependencies" in resp.json()["detail"]
        assert blocker_id in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_session_succeeds_once_dependency_done(self, authed_client, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-from-env")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake")

        blocker = await authed_client.post("/api/tasks", json={"title": "Blocker", "review_gate": "none"})
        blocker_id = blocker.json()["id"]
        await authed_client.patch(f"/api/tasks/{blocker_id}", json={"status": "in_progress"})
        await authed_client.patch(f"/api/tasks/{blocker_id}", json={"status": "done"})

        blocked = await authed_client.post("/api/tasks", json={
            "title": "Blocked", "status": "open", "dependencies": [blocker_id],
        })
        blocked_id = blocked.json()["id"]

        resp = await authed_client.post("/api/sessions", json={"prompt": "", "task_id": blocked_id})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patch_to_in_progress_refused_when_blocked(self, authed_client):
        """Dragging a Kanban card straight into 'In progress' must respect
        the same gate as starting a session — not just a session-creation
        pre-flight check."""
        blocker = await authed_client.post("/api/tasks", json={"title": "Blocker"})
        blocker_id = blocker.json()["id"]
        blocked = await authed_client.post("/api/tasks", json={
            "title": "Blocked", "status": "open", "dependencies": [blocker_id],
        })
        blocked_id = blocked.json()["id"]

        resp = await authed_client.patch(f"/api/tasks/{blocked_id}", json={"status": "in_progress"})
        assert resp.status_code == 400
        assert "blocked by unfinished dependencies" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_tasks_flags_blocked_by_deps(self, authed_client):
        blocker = await authed_client.post("/api/tasks", json={"title": "Blocker"})
        blocker_id = blocker.json()["id"]
        await authed_client.post("/api/tasks", json={
            "title": "Blocked", "status": "open", "dependencies": [blocker_id],
        })

        resp = await authed_client.get("/api/tasks")
        by_title = {t["title"]: t for t in resp.json()["tasks"]}
        assert by_title["Blocked"]["blocked_by_deps"] is True
        assert by_title["Blocker"]["blocked_by_deps"] is False


class TestAgentDetailAPI:
    @pytest.mark.asyncio
    async def test_get_unknown_agent_404s(self, authed_client):
        resp = await authed_client.get("/api/agent/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_checkpoint_unknown_agent_404s(self, authed_client):
        resp = await authed_client.post("/api/agent/nonexistent/checkpoint", json={"label": "x"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_revert_unknown_agent_404s(self, authed_client):
        resp = await authed_client.post("/api/agent/nonexistent/revert", json={"label": "x"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_interrupt_unknown_agent_404s(self, authed_client):
        resp = await authed_client.post("/api/agent/nonexistent/interrupt")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_interrupt_noop_when_not_running_keeps_session(self, authed_client, session_manager):
        """Unlike DELETE, interrupt on an idle session is a no-op and the
        session is never removed."""
        from agent_knots.session.manager import Session
        session_manager._sessions["idle"] = Session(id="idle")
        resp = await authed_client.post("/api/agent/idle/interrupt")
        assert resp.status_code == 200
        assert "idle" in session_manager._sessions

    @pytest.mark.asyncio
    async def test_autonomous_unknown_agent_404s(self, authed_client):
        resp = await authed_client.post("/api/agent/nonexistent/autonomous", json={"on": False})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_autonomous_off_sets_assistant_mode(self, authed_client, session_manager):
        from agent_knots.session.manager import Session
        session_manager._sessions["s1"] = Session(id="s1", mode="agent")
        resp = await authed_client.post("/api/agent/s1/autonomous", json={"on": False})
        assert resp.status_code == 200
        assert session_manager._sessions["s1"].mode == "assistant"

    @pytest.mark.asyncio
    async def test_autonomous_on_without_task_sets_agent_mode(self, authed_client, session_manager):
        from agent_knots.session.manager import Session
        session_manager._sessions["s2"] = Session(id="s2", mode="assistant", task_id=None)
        resp = await authed_client.post("/api/agent/s2/autonomous", json={"on": True})
        assert resp.status_code == 200
        assert session_manager._sessions["s2"].mode == "agent"


class TestAgentFileAPI:
    """Files tab preview — reads a file's content confined to the
    session's own working directory, no real agent/network involved."""

    @pytest.fixture
    def workspace_session(self, session_manager, tmp_path):
        from agent_knots.session.manager import Session
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "README.md").write_text("# Hello\n\nSome markdown content.")
        (ws / "notes" / "sub").mkdir(parents=True)
        (ws / "notes" / "sub" / "deep.txt").write_text("nested file")
        (ws / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00binary\xff\xfe")
        session = Session(id="test-session", working_dir=str(ws))
        session_manager._sessions[session.id] = session
        return ws

    @pytest.mark.asyncio
    async def test_get_file_unknown_agent_404s(self, authed_client):
        resp = await authed_client.get("/api/agent/nonexistent/file?path=README.md")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_file_with_no_working_dir_reads_absolute_path(self, authed_client, session_manager, tmp_path):
        """A session with no workspace never had its shell/editor tools
        sandboxed either — they already read/write anywhere on disk
        unconfined, so the preview shouldn't refuse a file just because
        there's no workspace concept for this session."""
        from agent_knots.session.manager import Session
        f = tmp_path / "myfile.txt"
        f.write_text("no workspace, still readable")
        session_manager._sessions["no-ws"] = Session(id="no-ws", working_dir=None)
        resp = await authed_client.get(f"/api/agent/no-ws/file?path={f}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "no workspace, still readable"

    @pytest.mark.asyncio
    async def test_get_file_with_no_working_dir_and_missing_file_404s(self, authed_client, session_manager):
        from agent_knots.session.manager import Session
        session_manager._sessions["no-ws"] = Session(id="no-ws", working_dir=None)
        resp = await authed_client.get("/api/agent/no-ws/file?path=/definitely/not/a/real/file.txt")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_file_reads_content(self, authed_client, workspace_session):
        resp = await authed_client.get("/api/agent/test-session/file?path=README.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == "# Hello\n\nSome markdown content."
        assert body["truncated"] is False

    @pytest.mark.asyncio
    async def test_get_file_reads_nested_path(self, authed_client, workspace_session):
        resp = await authed_client.get("/api/agent/test-session/file?path=notes/sub/deep.txt")
        assert resp.status_code == 200
        assert resp.json()["content"] == "nested file"

    @pytest.mark.asyncio
    async def test_get_file_not_found_404s(self, authed_client, workspace_session):
        resp = await authed_client.get("/api/agent/test-session/file?path=nope.txt")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_file_path_traversal_refused(self, authed_client, workspace_session):
        resp = await authed_client.get("/api/agent/test-session/file?path=../../../../etc/passwd")
        assert resp.status_code == 400
        assert "outside the workspace" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_file_binary_refused(self, authed_client, workspace_session):
        resp = await authed_client.get("/api/agent/test-session/file?path=image.png")
        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_get_file_truncates_large_files(self, authed_client, workspace_session):
        (workspace_session / "big.txt").write_text("x" * 600_000)
        resp = await authed_client.get("/api/agent/test-session/file?path=big.txt")
        assert resp.status_code == 200
        body = resp.json()
        assert body["truncated"] is True
        assert len(body["content"]) == 500_000


class TestTerminalWebSocket:
    """Real interactive terminal — a PTY-backed shell over a websocket.
    Uses starlette's synchronous TestClient (httpx.AsyncClient has no
    websocket support), so these are plain (non-async) test methods."""

    def test_invalid_token_rejected(self, session_manager, agent_knots_home):
        from starlette.testclient import TestClient
        client = TestClient(create_app(session_manager))
        with pytest.raises(Exception):
            with client.websocket_connect("/api/agent/whatever/terminal?token=wrong"):
                pass

    def test_unknown_agent_rejected(self, session_manager, agent_knots_home, auth_token):
        from starlette.testclient import TestClient
        client = TestClient(create_app(session_manager))
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/agent/nonexistent/terminal?token={auth_token}"):
                pass

    def test_real_shell_runs_command_in_working_dir(self, session_manager, agent_knots_home, auth_token, tmp_path):
        """End-to-end: spawn a real PTY shell rooted at the session's
        working_dir, send a command over the websocket, and read its
        actual output back — not mocked."""
        from starlette.testclient import TestClient
        from agent_knots.session.manager import Session

        (tmp_path / "marker.txt").write_text("")
        session = Session(id="term-test", working_dir=str(tmp_path))
        session_manager._sessions[session.id] = session

        client = TestClient(create_app(session_manager))
        with client.websocket_connect(f"/api/agent/term-test/terminal?token={auth_token}") as ws:
            ws.send_json({"type": "input", "data": "echo hello_from_pty && pwd\n"})
            output = ""
            for _ in range(100):
                msg = ws.receive_json()
                output += msg.get("data", "")
                if "hello_from_pty" in output and str(tmp_path) in output:
                    break
            assert "hello_from_pty" in output
            assert str(tmp_path) in output


class TestDraftTaskAPI:
    @pytest.mark.asyncio
    async def test_draft_blocked_when_unconfigured(self, authed_client):
        resp = await authed_client.post("/api/tasks/draft", json={"title": "Add dark mode"})
        assert resp.status_code == 400


class TestExtractJsonObject:
    """draft_task() doesn't pass response_format (not every OpenAI-compatible
    provider — e.g. MiniMax — supports that strict-JSON-mode param), so the
    completion text has to be parsed leniently instead."""

    def test_plain_json(self):
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_markdown_code_fence(self):
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        text = '```json\n{"a": 1}\n```'
        assert _extract_json_object(text) == {"a": 1}

    def test_plain_code_fence_no_language(self):
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        text = '```\n{"a": 1}\n```'
        assert _extract_json_object(text) == {"a": 1}

    def test_stray_commentary_around_json(self):
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        text = 'Sure, here you go:\n{"a": 1}\nHope that helps!'
        assert _extract_json_object(text) == {"a": 1}

    def test_no_json_raises(self):
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        with pytest.raises(Exception):
            _extract_json_object("no json here at all")

    def test_think_block_before_json_is_stripped(self):
        """MiniMax M2.7 (a reasoning model) inlines a <think>...</think>
        block directly into a plain completion's message.content — there's
        no separate reasoning field to read instead."""
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        text = '<think>Let me plan this out...</think>\n{"a": 1}'
        assert _extract_json_object(text) == {"a": 1}

    def test_think_block_containing_braces_does_not_break_extraction(self):
        """Regression: a naive "first { to last }" scan grabs braces from
        *inside* the reasoning (very plausible when the reasoning discusses
        code or gives JSON examples) instead of the real object, producing
        text that isn't valid JSON at all and a cryptic raw json.JSONDecodeError
        ("Expecting value: line 1 column 1 (char 0)") instead of a clear one."""
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        text = (
            '<think>Something like {"example": "not the real answer"} maybe? '
            'Let me reconsider.</think>\n'
            '{"a": 1}'
        )
        assert _extract_json_object(text) == {"a": 1}

    def test_unparseable_text_raises_with_a_clear_message(self):
        """Even after stripping think-blocks/fences, genuinely broken JSON
        must raise a ValueError with an actionable message — not let a raw
        json.JSONDecodeError bubble up uncaught."""
        from agent_knots.cockpit.web.jsonutil import _extract_json_object
        with pytest.raises(ValueError, match="No valid JSON object found"):
            _extract_json_object('<think>{unbalanced</think>{"a": broken}')


class TestSPAFallback:
    @pytest.mark.asyncio
    async def test_unknown_path_serves_spa_shell(self, authed_client):
        """BrowserRouter paths like /tasks/T-123 must serve the SPA shell
        on a hard refresh, not 404."""
        resp = await authed_client.get("/tasks/T-123")
        assert resp.status_code == 200
        assert "agent-knots" in resp.text

    @pytest.mark.asyncio
    async def test_unknown_api_path_still_404s(self, authed_client):
        """The catch-all must not shadow /api/* — it's registered last,
        but still needs its own belt-and-suspenders check."""
        resp = await authed_client.get("/api/nonexistent")
        assert resp.status_code == 404


class TestWorkspaceAPI:
    @pytest.mark.asyncio
    async def test_auto_assign_and_max_concurrent_defaults(self, authed_client):
        await authed_client.post("/api/workspaces", json={"id": "ws1", "name": "WS1"})
        resp = await authed_client.get("/api/workspaces")
        ws = next(w for w in resp.json()["workspaces"] if w["id"] == "ws1")
        assert ws["auto_assign"] is False
        assert ws["max_concurrent"] == 2

    @pytest.mark.asyncio
    async def test_auto_assign_and_max_concurrent_round_trip(self, authed_client):
        await authed_client.post("/api/workspaces", json={
            "id": "ws2", "name": "WS2", "auto_assign": True, "max_concurrent": 5,
        })
        await authed_client.patch("/api/workspaces/ws2", json={"max_concurrent": 3})
        resp = await authed_client.get("/api/workspaces")
        ws = next(w for w in resp.json()["workspaces"] if w["id"] == "ws2")
        assert ws["auto_assign"] is True
        assert ws["max_concurrent"] == 3

    @pytest.mark.asyncio
    async def test_create_without_id_slugifies_name(self, authed_client):
        resp = await authed_client.post("/api/workspaces", json={"name": "My Cool Project!"})
        assert resp.status_code == 200
        assert resp.json()["id"] == "my-cool-project"

        listed = await authed_client.get("/api/workspaces")
        assert any(w["id"] == "my-cool-project" and w["name"] == "My Cool Project!" for w in listed.json()["workspaces"])

    @pytest.mark.asyncio
    async def test_create_without_id_dedupes_slug_collisions(self, authed_client):
        await authed_client.post("/api/workspaces", json={"name": "Dupe"})
        resp = await authed_client.post("/api/workspaces", json={"name": "Dupe"})
        assert resp.status_code == 200
        assert resp.json()["id"] == "dupe-2"

    @pytest.mark.asyncio
    async def test_get_single_workspace(self, authed_client):
        await authed_client.post("/api/workspaces", json={"id": "ws-single", "name": "Single WS", "repository": "/tmp/x"})
        resp = await authed_client.get("/api/workspaces/ws-single")
        assert resp.status_code == 200
        assert resp.json() == {
            "id": "ws-single", "name": "Single WS", "description": "", "repository": "/tmp/x",
            # No managed=true in the POST, so the path is used verbatim
            # and nothing is cloned — the pre-managed-workspaces path.
            "source": "", "managed": False,
            "runtime": "", "provider": "", "tags": [], "auto_assign": False, "max_concurrent": 2, "archived": False,
            "created_at": resp.json()["created_at"],
        }

    @pytest.mark.asyncio
    async def test_get_single_workspace_not_found_404s(self, authed_client):
        resp = await authed_client.get("/api/workspaces/nonexistent")
        assert resp.status_code == 404


class TestManagedWorkspaces:
    """A managed workspace is one whose directory agent-knots created
    under config.workspaces_root(), rather than a path the user already
    had. The agent_knots_home fixture points AGENT_KNOTS_HOME at
    tmp_path, and workspaces_root() follows it, so all of this stays
    inside the test's own directory.
    """

    def _source_repo(self, tmp_path, name="upstream"):
        repo = tmp_path / name
        repo.mkdir()
        # -b main so the branch name doesn't depend on the developer's
        # init.defaultBranch.
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "a.txt").write_text("hello\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
        return repo

    @pytest.mark.asyncio
    async def test_clones_into_a_folder_named_after_the_repo(self, authed_client, tmp_path):
        source = self._source_repo(tmp_path)
        resp = await authed_client.post("/api/workspaces", json={
            "id": "managed-1", "name": "Managed One",
            "repository": str(source), "managed": True,
        })
        assert resp.status_code == 200, resp.text

        repository = Path(resp.json()["repository"])
        # Named for the repo, not the workspace slug — the path should
        # look like a normal `git clone` when you cd into it.
        assert repository.name == "upstream"
        assert repository.parent == tmp_path / "workspaces"
        assert (repository / "a.txt").read_text() == "hello\n"

    @pytest.mark.asyncio
    async def test_the_users_own_checkout_is_left_alone(self, authed_client, tmp_path):
        """The whole point: the agent gets a copy, you keep yours."""
        source = self._source_repo(tmp_path)
        before = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=source,
            capture_output=True, text=True,
        ).stdout

        await authed_client.post("/api/workspaces", json={
            "id": "managed-2", "name": "Managed Two",
            "repository": str(source), "managed": True,
        })

        after = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=source,
            capture_output=True, text=True,
        ).stdout
        assert after == before
        assert subprocess.run(
            ["git", "status", "--porcelain"], cwd=source, capture_output=True, text=True,
        ).stdout == ""

    @pytest.mark.asyncio
    async def test_two_workspaces_on_the_same_repo_name_get_distinct_folders(
        self, authed_client, tmp_path,
    ):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        first = self._source_repo(tmp_path / "a", "shared-name")
        second = self._source_repo(tmp_path / "b", "shared-name")

        r1 = await authed_client.post("/api/workspaces", json={
            "id": "dup-1", "name": "Dup One", "repository": str(first), "managed": True})
        r2 = await authed_client.post("/api/workspaces", json={
            "id": "dup-2", "name": "Dup Two", "repository": str(second), "managed": True})

        assert Path(r1.json()["repository"]).name == "shared-name"
        assert Path(r2.json()["repository"]).name == "shared-name-2"

    @pytest.mark.asyncio
    async def test_a_failed_clone_leaves_no_workspace_and_no_directory(
        self, authed_client, tmp_path,
    ):
        """Provisioning happens before the record exists precisely so a
        failure can't strand either half."""
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()

        resp = await authed_client.post("/api/workspaces", json={
            "id": "doomed", "name": "Doomed", "repository": str(not_a_repo), "managed": True,
        })
        assert resp.status_code == 400
        assert "not a git repository" in resp.json()["detail"]

        assert (await authed_client.get("/api/workspaces/doomed")).status_code == 404
        assert not (tmp_path / "workspaces" / "plain-dir").exists()

    @pytest.mark.asyncio
    async def test_no_repository_still_gets_a_real_shared_folder(self, authed_client, tmp_path):
        """A workspace with no repo used to get no folder at all —
        sessions fell through to a per-session workdir under the hidden
        home, so nothing persisted and two sessions never saw the same
        files."""
        resp = await authed_client.post("/api/workspaces", json={
            "id": "notebook", "name": "Notebook", "managed": True,
        })
        assert resp.status_code == 200

        repository = Path(resp.json()["repository"])
        assert repository == tmp_path / "workspaces" / "notebook"
        assert repository.is_dir()
        # Off by default: Review works without git, so an empty
        # workspace has no need of a repo it never asked for.
        assert not (repository / ".git").exists()

    @pytest.mark.asyncio
    async def test_init_git_opts_an_empty_workspace_into_a_repo(self, authed_client, tmp_path):
        resp = await authed_client.post("/api/workspaces", json={
            "id": "fresh-code", "name": "Fresh Code", "managed": True, "init_git": True,
        })
        assert (Path(resp.json()["repository"]) / ".git").is_dir()

    @pytest.mark.asyncio
    async def test_unmanaged_is_the_api_default_and_uses_the_path_verbatim(
        self, authed_client, tmp_path,
    ):
        """Back-compat: an existing caller that passes a path still gets
        that exact path, and nothing is cloned anywhere."""
        source = self._source_repo(tmp_path)
        resp = await authed_client.post("/api/workspaces", json={
            "id": "legacy", "name": "Legacy", "repository": str(source),
        })
        assert resp.json()["repository"] == str(source)
        assert resp.json()["managed"] is False
        assert not (tmp_path / "workspaces" / "upstream").exists()

    @pytest.mark.asyncio
    async def test_managed_repository_cannot_be_repointed(self, authed_client, tmp_path):
        source = self._source_repo(tmp_path)
        await authed_client.post("/api/workspaces", json={
            "id": "pinned", "name": "Pinned", "repository": str(source), "managed": True})

        resp = await authed_client.patch(
            "/api/workspaces/pinned", json={"repository": "/somewhere/else"},
        )
        assert resp.status_code == 400
        assert "managed by agent-knots" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_unmanaged_repository_can_still_be_edited(self, authed_client, tmp_path):
        await authed_client.post("/api/workspaces", json={
            "id": "editable", "name": "Editable", "repository": "/tmp/one"})
        resp = await authed_client.patch(
            "/api/workspaces/editable", json={"repository": "/tmp/two"},
        )
        assert resp.status_code == 200
        after = (await authed_client.get("/api/workspaces/editable")).json()
        assert after["repository"] == "/tmp/two"

    @pytest.mark.asyncio
    async def test_delete_keeps_the_clone_on_disk_by_default(self, authed_client, tmp_path):
        """That folder is real code, possibly never pushed anywhere.
        Losing a workspace record must not mean losing the work."""
        source = self._source_repo(tmp_path)
        created = await authed_client.post("/api/workspaces", json={
            "id": "keepme", "name": "Keep Me", "repository": str(source), "managed": True})
        repository = Path(created.json()["repository"])

        resp = await authed_client.delete("/api/workspaces/keepme")
        assert resp.status_code == 200
        assert resp.json()["removed_files"] is False
        assert repository.is_dir()

    @pytest.mark.asyncio
    async def test_delete_files_removes_a_managed_clone_when_asked(self, authed_client, tmp_path):
        source = self._source_repo(tmp_path)
        created = await authed_client.post("/api/workspaces", json={
            "id": "binme", "name": "Bin Me", "repository": str(source), "managed": True})
        repository = Path(created.json()["repository"])

        resp = await authed_client.delete("/api/workspaces/binme", params={"delete_files": "true"})
        assert resp.json()["removed_files"] is True
        assert not repository.exists()
        # The source it was cloned from is somebody else's property.
        assert source.is_dir()

    @pytest.mark.asyncio
    async def test_delete_files_never_touches_an_unmanaged_folder(self, authed_client, tmp_path):
        source = self._source_repo(tmp_path)
        await authed_client.post("/api/workspaces", json={
            "id": "theirs", "name": "Theirs", "repository": str(source)})

        resp = await authed_client.delete("/api/workspaces/theirs", params={"delete_files": "true"})
        assert resp.json()["removed_files"] is False
        assert source.is_dir()

    @pytest.mark.asyncio
    async def test_push_reports_a_missing_remote_rather_than_failing_opaquely(
        self, authed_client, tmp_path,
    ):
        source = self._source_repo(tmp_path)
        await authed_client.post("/api/workspaces", json={
            "id": "nopush", "name": "No Push", "repository": str(source)})

        resp = await authed_client.post(
            "/api/workspaces/nopush/push", json={"branch": "main"},
        )
        assert resp.status_code == 400
        assert "remote" in resp.json()["detail"]


class TestWorkspaceBackCompat:
    @pytest.mark.asyncio
    async def test_workspace_yaml_written_before_managed_clones_still_loads(
        self, authed_client, agent_knots_home,
    ):
        """Pre-existing workspaces have neither `source` nor `managed`
        in their YAML. They must keep working, unmanaged, pointing
        exactly where they already pointed."""
        from agent_knots.yamlfile import atomic_write_yaml

        projects = agent_knots_home / "projects"
        projects.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(projects / "old-ws.yaml", {
            "id": "old-ws", "name": "Old Workspace", "description": "from before",
            "repository": "/home/someone/code/thing", "default_branch": "main",
            "runtime": "", "provider": "", "tags": [], "auto_assign": False,
            "max_concurrent": 2, "archived": False,
            "created_at": 1700000000.0, "updated_at": 1700000000.0,
        })

        resp = await authed_client.get("/api/workspaces/old-ws")
        assert resp.status_code == 200
        assert resp.json()["repository"] == "/home/someone/code/thing"
        assert resp.json()["managed"] is False
        assert resp.json()["source"] == ""


class TestFilesystemBrowseAPI:
    @pytest.mark.asyncio
    async def test_browse_lists_subdirectories_only(self, authed_client, tmp_path):
        # A nested dir, not tmp_path itself — tmp_path is also where the
        # agent_knots_home fixture points AGENT_KNOTS_HOME, so it already
        # has its own subdirectories (vault/, sessions/, etc.) by the
        # time authed_client has made its first request.
        root = tmp_path / "browse-root"
        root.mkdir()
        (root / "repo-a").mkdir()
        (root / "repo-b").mkdir()
        (root / "a-file.txt").write_text("x")
        (root / ".hidden").mkdir()

        resp = await authed_client.get("/api/fs/browse", params={"path": str(root)})
        assert resp.status_code == 200
        data = resp.json()
        names = {e["name"] for e in data["entries"]}
        assert names == {"repo-a", "repo-b"}
        assert data["path"] == str(root)
        assert data["parent"] == str(root.parent)

    @pytest.mark.asyncio
    async def test_browse_flags_git_repos(self, authed_client, tmp_path):
        repo = tmp_path / "a-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (tmp_path / "not-a-repo").mkdir()

        resp = await authed_client.get("/api/fs/browse", params={"path": str(tmp_path)})
        entries = {e["name"]: e["is_git"] for e in resp.json()["entries"]}
        assert entries["a-repo"] is True
        assert entries["not-a-repo"] is False

    @pytest.mark.asyncio
    async def test_browse_nonexistent_path_400s(self, authed_client, tmp_path):
        resp = await authed_client.get("/api/fs/browse", params={"path": str(tmp_path / "nope")})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_browse_defaults_to_home(self, authed_client):
        resp = await authed_client.get("/api/fs/browse")
        assert resp.status_code == 200


class TestFsGitInfoAPI:
    @pytest.mark.asyncio
    async def test_non_git_directory(self, authed_client, tmp_path):
        resp = await authed_client.get("/api/fs/git-info", params={"path": str(tmp_path)})
        assert resp.json() == {"is_git": False, "github_url": None}

    @pytest.mark.asyncio
    async def test_git_repo_no_remote(self, authed_client, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path)
        resp = await authed_client.get("/api/fs/git-info", params={"path": str(tmp_path)})
        data = resp.json()
        assert data["is_git"] is True
        assert data["github_url"] is None

    @pytest.mark.asyncio
    async def test_git_repo_with_https_github_remote(self, authed_client, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path)
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/jamiedf/agent-knots.git"], cwd=tmp_path)
        resp = await authed_client.get("/api/fs/git-info", params={"path": str(tmp_path)})
        data = resp.json()
        assert data["is_git"] is True
        assert data["github_url"] == "https://github.com/jamiedf/agent-knots"

    @pytest.mark.asyncio
    async def test_git_repo_with_ssh_github_remote(self, authed_client, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:jamiedf/agent-knots.git"], cwd=tmp_path)
        resp = await authed_client.get("/api/fs/git-info", params={"path": str(tmp_path)})
        assert resp.json()["github_url"] == "https://github.com/jamiedf/agent-knots"

    @pytest.mark.asyncio
    async def test_git_repo_with_non_github_remote(self, authed_client, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path)
        subprocess.run(["git", "remote", "add", "origin", "https://gitlab.com/jamiedf/agent-knots.git"], cwd=tmp_path)
        resp = await authed_client.get("/api/fs/git-info", params={"path": str(tmp_path)})
        data = resp.json()
        assert data["is_git"] is True
        assert data["github_url"] is None


class TestStagesAPI:
    @pytest.mark.asyncio
    async def test_list_returns_defaults(self, authed_client):
        resp = await authed_client.get("/api/stages")
        stages = resp.json()["stages"]
        assert [s["key"] for s in stages] == ["draft", "open", "in_progress", "review", "done", "abandoned"]
        abandoned = next(s for s in stages if s["key"] == "abandoned")
        assert abandoned["enabled"] is False

    @pytest.mark.asyncio
    async def test_toggle_persists(self, authed_client):
        await authed_client.post("/api/stages/abandoned/toggle", json={"enabled": True})
        resp = await authed_client.get("/api/stages")
        abandoned = next(s for s in resp.json()["stages"] if s["key"] == "abandoned")
        assert abandoned["enabled"] is True

    @pytest.mark.asyncio
    async def test_toggle_required_stage_off_400s(self, authed_client):
        resp = await authed_client.post("/api/stages/draft/toggle", json={"enabled": False})
        assert resp.status_code == 400


class TestRolesAPI:
    @pytest.mark.asyncio
    async def test_list_returns_defaults_all_disabled(self, authed_client):
        resp = await authed_client.get("/api/roles")
        roles = resp.json()["roles"]
        assert [r["key"] for r in roles] == ["planner", "builder", "reviewer"]
        assert all(not r["enabled"] for r in roles)

    @pytest.mark.asyncio
    async def test_update_persists(self, authed_client):
        resp = await authed_client.patch("/api/roles/builder", json={"enabled": True, "model": "gpt-4o"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        assert resp.json()["model"] == "gpt-4o"

        listed = await authed_client.get("/api/roles")
        builder = next(r for r in listed.json()["roles"] if r["key"] == "builder")
        assert builder["enabled"] is True
        assert builder["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_update_unknown_role_404s(self, authed_client):
        resp = await authed_client.patch("/api/roles/nonexistent", json={"enabled": True})
        assert resp.status_code == 404


class TestRoleTriggers:
    @pytest.mark.asyncio
    async def test_enabled_role_fires_on_matching_transition(self, authed_client, session_manager, monkeypatch):
        """Enabling "builder" (trigger=is_started) and moving a task from
        draft to in_progress should auto-start a session — the trigger
        wiring in update_task()'s PATCH handler."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        await authed_client.patch("/api/roles/builder", json={"enabled": True})
        created = await authed_client.post("/api/tasks", json={"title": "Trigger test"})
        task_id = created.json()["id"]

        before = len(session_manager.active)
        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
        assert resp.status_code == 200

        # The trigger fires a fire-and-forget asyncio task — give the
        # event loop a turn to run it before asserting.
        for _ in range(5):
            await asyncio.sleep(0.05)
            if len(session_manager.active) > before:
                break
        assert len(session_manager.active) > before

    @pytest.mark.asyncio
    async def test_draft_to_in_progress_fires_both_leaves_draft_and_is_started(self, authed_client, session_manager, monkeypatch):
        """Regression: a task now starts in Draft, so a single PATCH can
        jump straight from draft to in_progress, skipping Open entirely.
        That must fire *both* leaves_draft (planner) and is_started
        (builder), not just whichever came first in an if/elif chain."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        await authed_client.patch("/api/roles/planner", json={"enabled": True})
        await authed_client.patch("/api/roles/builder", json={"enabled": True})
        created = await authed_client.post("/api/tasks", json={"title": "Dual trigger test"})
        task_id = created.json()["id"]
        assert created.json()["status"] == "draft"

        before = len(session_manager.active)
        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
        assert resp.status_code == 200

        for _ in range(5):
            await asyncio.sleep(0.05)
            if len(session_manager.active) - before >= 2:
                break
        assert len(session_manager.active) - before == 2

    @pytest.mark.asyncio
    async def test_disabled_role_does_not_fire(self, authed_client, session_manager):
        """Roles are disabled by default — no trigger should fire."""
        created = await authed_client.post("/api/tasks", json={"title": "No trigger test"})
        task_id = created.json()["id"]

        before = len(session_manager.active)
        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
        await asyncio.sleep(0.1)
        assert len(session_manager.active) == before

    @pytest.mark.asyncio
    async def test_role_fired_session_gets_the_tasks_workspace_as_working_dir(
        self, authed_client, session_manager, tmp_path, monkeypatch,
    ):
        """Regression: role-fired sessions used to pass neither project_id
        nor working_dir, so a builder role's shell/editor tools ran
        against whatever cwd agent-knots itself started from — not the
        task's actual repo. task.project is the workspace id; it must
        reach SessionManager.start() as project_id."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        await authed_client.post(
            "/api/workspaces", json={"id": "ws-role", "name": "WS", "repository": str(workspace_dir)},
        )
        await authed_client.patch("/api/roles/builder", json={"enabled": True})
        created = await authed_client.post(
            "/api/tasks", json={"title": "Needs the right cwd", "project": "ws-role"},
        )
        task_id = created.json()["id"]

        before = {s.id for s in session_manager.active}
        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
        for _ in range(5):
            await asyncio.sleep(0.05)
            new = [s for s in session_manager.active if s.id not in before]
            if new:
                break
        assert new
        assert new[0].working_dir == str(workspace_dir)

    @pytest.mark.asyncio
    async def test_advisory_role_gets_allowlisted_and_does_not_steal_assignment(
        self, authed_client, session_manager, monkeypatch,
    ):
        """The reviewer role is advisory: it should get Session.
        allowed_tools from its own tools list, and — since assign() is
        last-writer-wins — must not overwrite assigned_to and knock the
        actual writer off the task."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        await authed_client.patch("/api/roles/builder", json={"enabled": True})
        await authed_client.patch("/api/roles/reviewer", json={"enabled": True})
        created = await authed_client.post("/api/tasks", json={"title": "Review me"})
        task_id = created.json()["id"]

        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
        for _ in range(5):
            await asyncio.sleep(0.05)
            task = (await authed_client.get(f"/api/tasks/{task_id}")).json()
            if task["assigned_to"]:
                break
        writer_id = task["assigned_to"]
        assert writer_id

        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "review"})
        for _ in range(5):
            await asyncio.sleep(0.05)
            reviewer_sessions = [
                s for s in session_manager.active if s.task_id == task_id and s.advisory
            ]
            if reviewer_sessions:
                break
        assert reviewer_sessions
        reviewer = reviewer_sessions[0]
        assert reviewer.allowed_tools == {"read_task", "mark_criterion_met", "log_progress"}
        assert reviewer.role == "reviewer"

        # The writer must still be the assignee — the advisory session
        # never should have touched it.
        task = (await authed_client.get(f"/api/tasks/{task_id}")).json()
        assert task["assigned_to"] == writer_id


class TestAutoStopOnTerminalStatus:
    """A task's session(s) must stop automatically once the task reaches
    review/done/abandoned — otherwise nothing ever stops a finished
    session, and its branch/workdir sit around forever. See
    _maybe_auto_stop_finished_sessions in routes/tasks.py."""

    @pytest.mark.asyncio
    async def test_reaching_done_stops_the_session(self, authed_client, session_manager, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        created = await authed_client.post(
            "/api/tasks", json={"title": "Auto-stop on done", "review_gate": "none"},
        )
        task_id = created.json()["id"]
        session = await authed_client.post(
            "/api/sessions", json={"prompt": "", "mode": "agent", "task_id": task_id},
        )
        session_id = session.json()["id"]
        assert session_manager.get(session_id) is not None

        resp = await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        assert resp.status_code == 200
        assert session_manager.get(session_id) is None

    @pytest.mark.asyncio
    async def test_reaching_review_pauses_rather_than_stops_the_session(self, authed_client, session_manager, monkeypatch):
        """review pauses (interrupts + mode=assistant) instead of
        stopping — the session stays alive so the Review screen's
        reject flow can resume the same thread with feedback, rather
        than losing the whole conversation and starting fresh."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        created = await authed_client.post("/api/tasks", json={"title": "Pause on review"})
        task_id = created.json()["id"]
        session = await authed_client.post(
            "/api/sessions", json={"prompt": "", "mode": "agent", "task_id": task_id},
        )
        session_id = session.json()["id"]

        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "review"})
        paused = session_manager.get(session_id)
        assert paused is not None
        assert paused.mode == "assistant"

    @pytest.mark.asyncio
    async def test_reaching_abandoned_stops_the_session(self, authed_client, session_manager, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        created = await authed_client.post("/api/tasks", json={"title": "Auto-stop on abandon"})
        task_id = created.json()["id"]
        session = await authed_client.post(
            "/api/sessions", json={"prompt": "", "mode": "agent", "task_id": task_id},
        )
        session_id = session.json()["id"]

        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "abandoned"})
        assert session_manager.get(session_id) is None

    @pytest.mark.asyncio
    async def test_non_terminal_transition_does_not_stop_the_session(
        self, authed_client, session_manager, monkeypatch,
    ):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        created = await authed_client.post("/api/tasks", json={"title": "Still working"})
        task_id = created.json()["id"]
        session = await authed_client.post(
            "/api/sessions", json={"prompt": "", "mode": "agent", "task_id": task_id},
        )
        session_id = session.json()["id"]

        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "blocked"})
        assert session_manager.get(session_id) is not None

    @pytest.mark.asyncio
    async def test_pausing_writer_on_review_does_not_disturb_the_new_reviewer_it_just_fired(
        self, authed_client, session_manager, monkeypatch,
    ):
        """The transition into 'review' both pauses the old writer AND
        (if the reviewer role is enabled) fires a brand new advisory
        session. Ordering matters: the pause must run before the new
        session exists, or it could catch and immediately pause it too."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        await authed_client.patch("/api/roles/reviewer", json={"enabled": True})
        created = await authed_client.post("/api/tasks", json={"title": "Review with pause"})
        task_id = created.json()["id"]
        writer = await authed_client.post(
            "/api/sessions", json={"prompt": "", "mode": "agent", "task_id": task_id},
        )
        writer_id = writer.json()["id"]

        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "review"})

        writer_session = session_manager.get(writer_id)
        assert writer_session is not None
        assert writer_session.mode == "assistant"
        for _ in range(10):
            await asyncio.sleep(0.05)
            reviewers = [s for s in session_manager.active if s.task_id == task_id and s.advisory]
            if reviewers:
                break
        assert reviewers, "the new advisory reviewer session must survive the same pause call"
        assert reviewers[0].mode == "agent", "the pause must not also catch the brand new reviewer session"


class TestTaskAgentsAPI:
    @pytest.mark.asyncio
    async def test_lists_only_sessions_for_this_task(self, authed_client, session_manager, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        await authed_client.patch("/api/roles/builder", json={"enabled": True})
        t1 = (await authed_client.post("/api/tasks", json={"title": "T1"})).json()["id"]
        t2 = (await authed_client.post("/api/tasks", json={"title": "T2"})).json()["id"]

        await authed_client.patch(f"/api/tasks/{t1}", json={"status": "in_progress"})
        for _ in range(5):
            await asyncio.sleep(0.05)
            if any(s.task_id == t1 for s in session_manager.active):
                break

        resp = await authed_client.get(f"/api/tasks/{t1}/agents")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        assert len(agents) == 1
        assert agents[0]["task_id"] == t1
        assert agents[0]["role"] == "builder"
        assert agents[0]["advisory"] is False

        resp2 = await authed_client.get(f"/api/tasks/{t2}/agents")
        assert resp2.json()["agents"] == []

    @pytest.mark.asyncio
    async def test_unknown_task_returns_empty_list_not_404(self, authed_client):
        """No agents for an unknown task is indistinguishable from no
        agents for a real-but-idle task — this is a session lookup, not
        a task lookup, so it never needs to 404."""
        resp = await authed_client.get("/api/tasks/nonexistent/agents")
        assert resp.status_code == 200
        assert resp.json()["agents"] == []


class TestReviewAPI:
    """Review is now task-keyed, not workspace-keyed — every test sets
    up a task assigned to a workspace/repo, checked out on the exact
    branch _task_branch falls back to when there's no live session
    (gitutil.session_branch_name), since these tests never start a real
    agent session.

    Everything here is the git-backed path; TestReviewWithoutGit covers
    the same flow for a workspace that isn't a repo."""

    async def _reviewable_task(self, authed_client, tmp_path, ws_id, title="Review test task"):
        from agent_knots.gitutil import session_branch_name

        repo = tmp_path / ws_id
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        await authed_client.post("/api/workspaces", json={"id": ws_id, "name": ws_id, "repository": str(repo)})
        task = (await authed_client.post("/api/tasks", json={"title": title, "project": ws_id})).json()
        branch = session_branch_name(task["id"], title, "")
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, capture_output=True)

        resp = await authed_client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})
        assert resp.status_code == 200
        return task, repo, branch

    @pytest.mark.asyncio
    async def test_list_tasks_empty_when_none_in_review(self, authed_client):
        resp = await authed_client.get("/api/review/tasks")
        assert resp.status_code == 200
        assert resp.json()["tasks"] == []

    @pytest.mark.asyncio
    async def test_list_tasks_includes_a_task_in_review(self, authed_client, tmp_path):
        task, _repo, branch = await self._reviewable_task(authed_client, tmp_path, "rt1")
        tasks = (await authed_client.get("/api/review/tasks")).json()["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["id"] == task["id"]
        assert tasks[0]["branch"] == branch
        assert tasks[0]["project"] == "rt1"

    @pytest.mark.asyncio
    async def test_list_diffs_from_real_git_repo(self, authed_client, tmp_path):
        task, repo, _branch = await self._reviewable_task(authed_client, tmp_path, "rt2")
        (repo / "a.txt").write_text("one\ntwo\n")

        resp = await authed_client.get("/api/review/diffs", params={"task_id": task["id"]})
        diffs = resp.json()["diffs"]
        assert len(diffs) == 1
        assert diffs[0]["file"] == "a.txt"
        assert diffs[0]["added"] == 1

    @pytest.mark.asyncio
    async def test_approve_commits_the_file(self, authed_client, tmp_path):
        task, repo, _branch = await self._reviewable_task(authed_client, tmp_path, "rt3")
        (repo / "a.txt").write_text("one\ntwo\n")

        resp = await authed_client.post("/api/review/approve", json={"task_id": task["id"], "file": "a.txt"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "committed"

        # No longer a pending diff, and git log shows the new commit.
        diffs = (await authed_client.get("/api/review/diffs", params={"task_id": task["id"]})).json()["diffs"]
        assert diffs == []
        log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True)
        assert log.stdout.count("\n") == 2

    @pytest.mark.asyncio
    async def test_approve_all_moves_task_to_done_when_criteria_met(self, authed_client, tmp_path):
        task, repo, _branch = await self._reviewable_task(authed_client, tmp_path, "rt4")
        (repo / "a.txt").write_text("one\ntwo\n")

        resp = await authed_client.post("/api/review/approve", json={"task_id": task["id"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "committed"
        assert body["task_status"] == "done"

        updated = (await authed_client.get(f"/api/tasks/{task['id']}")).json()
        assert updated["status"] == "done"

    @pytest.mark.asyncio
    async def test_approve_all_refused_stays_in_review_when_criteria_unmet(self, authed_client, tmp_path):
        from agent_knots.gitutil import session_branch_name

        repo = tmp_path / "rt5"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        await authed_client.post("/api/workspaces", json={"id": "rt5", "name": "rt5", "repository": str(repo)})
        task = (await authed_client.post(
            "/api/tasks", json={"title": "Needs criteria", "project": "rt5", "acceptance_criteria": ["Must pass"]},
        )).json()
        branch = session_branch_name(task["id"], "Needs criteria", "")
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, capture_output=True)
        await authed_client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})
        (repo / "a.txt").write_text("one\ntwo\n")

        resp = await authed_client.post("/api/review/approve", json={"task_id": task["id"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "committed"  # the commit itself still stands
        assert body["task_status"] == "review"
        assert "done_error" in body

        updated = (await authed_client.get(f"/api/tasks/{task['id']}")).json()
        assert updated["status"] == "review"

    @pytest.mark.asyncio
    async def test_reject_does_not_discard_changes_and_moves_task_back_to_in_progress(
        self, authed_client, monkeypatch, tmp_path,
    ):
        """Reject must never run a destructive git operation — confirmed
        by checking the file is untouched — but unlike the old
        workspace-wide queue's version, it's a real "send it back":
        the task moves back to in_progress. No live session here, so
        this also exercises reject's start-a-fresh-session fallback."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        task, repo, _branch = await self._reviewable_task(authed_client, tmp_path, "rt6")
        (repo / "a.txt").write_text("one\ntwo\n")

        resp = await authed_client.post(
            "/api/review/reject", json={"task_id": task["id"], "file": "a.txt", "reason": "wrong approach"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        assert body["task_status"] == "in_progress"

        # The uncommitted edit must still be there — reject didn't discard it.
        assert (repo / "a.txt").read_text() == "one\ntwo\n"
        diffs = (await authed_client.get("/api/review/diffs", params={"task_id": task["id"]})).json()["diffs"]
        assert len(diffs) == 1

        updated = (await authed_client.get(f"/api/tasks/{task['id']}")).json()
        assert updated["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_reject_resumes_the_same_paused_session_with_feedback(
        self, authed_client, session_manager, monkeypatch, tmp_path,
    ):
        """The whole point of pausing (not stopping) on review: reject
        picks the *same* thread back up with the reviewer's feedback,
        rather than starting a fresh session and losing all context."""
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        repo = tmp_path / "rt7"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        await authed_client.post("/api/workspaces", json={"id": "rt7", "name": "rt7", "repository": str(repo)})
        task = (await authed_client.post(
            "/api/tasks", json={"title": "Resume test", "project": "rt7"},
        )).json()
        session = (await authed_client.post(
            "/api/sessions", json={"prompt": "", "mode": "agent", "task_id": task["id"], "project_id": "rt7"},
        )).json()
        session_id = session["id"]

        (repo / "a.txt").write_text("one\ntwo\n")
        await authed_client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})
        assert session_manager.get(session_id).mode == "assistant"  # paused

        resp = await authed_client.post(
            "/api/review/reject", json={"task_id": task["id"], "file": "a.txt", "reason": "needs work"},
        )
        assert resp.status_code == 200
        assert resp.json()["session_id"] == session_id  # same session, not a new one

        resumed = session_manager.get(session_id)
        assert resumed is not None
        assert resumed.mode == "agent"

    @pytest.mark.asyncio
    async def test_approve_or_reject_on_task_not_in_review_400s(self, authed_client, tmp_path):
        repo = tmp_path / "rt8"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        await authed_client.post("/api/workspaces", json={"id": "rt8", "name": "rt8", "repository": str(repo)})
        task = (await authed_client.post("/api/tasks", json={"title": "Not in review", "project": "rt8"})).json()

        approve = await authed_client.post("/api/review/approve", json={"task_id": task["id"]})
        assert approve.status_code == 400
        reject = await authed_client.post("/api/review/reject", json={"task_id": task["id"], "reason": "x"})
        assert reject.status_code == 400

    @pytest.mark.asyncio
    async def test_approve_with_stale_branch_conflicts_and_does_not_commit(self, authed_client, tmp_path):
        """Regression guard: the working tree is shared across a
        workspace's sessions, so the branch a task's diffs live on
        could change out from under a review action if something else
        takes over the repo in between. Approve must refuse rather
        than commit onto whatever's checked out now."""
        task, repo, branch = await self._reviewable_task(authed_client, tmp_path, "rt9")
        (repo / "a.txt").write_text("one\ntwo\n")
        subprocess.run(["git", "checkout", "-q", "-b", "some-other-branch"], cwd=repo, capture_output=True)

        resp = await authed_client.post("/api/review/approve", json={"task_id": task["id"], "file": "a.txt"})
        assert resp.status_code == 409

        subprocess.run(["git", "checkout", "-q", branch], cwd=repo, capture_output=True)
        diffs = (await authed_client.get("/api/review/diffs", params={"task_id": task["id"]})).json()["diffs"]
        assert len(diffs) == 1

    @pytest.mark.asyncio
    async def test_approve_unknown_task_404s(self, authed_client):
        resp = await authed_client.post("/api/review/approve", json={"task_id": "nonexistent"})
        assert resp.status_code == 404


class TestReviewWithoutGit:
    """A workspace doesn't have to be a git repo — it can be a plain
    folder for writing, research or planning — and its tasks still need
    reviewing.

    Every test here is a regression test. Before Review was made
    git-optional, a task in a non-git workspace could enter review and
    never leave: approve and reject both 400'd on "Not a git
    repository", and the UI disabled both buttons because there were no
    pending files to act on.
    """

    async def _reviewable_task(self, authed_client, tmp_path, ws_id, criteria=None):
        folder = tmp_path / ws_id
        folder.mkdir()
        await authed_client.post("/api/workspaces", json={
            "id": ws_id, "name": ws_id, "repository": str(folder),
        })
        body = {"title": "Write the thing", "project": ws_id}
        if criteria is not None:
            body["acceptance_criteria"] = criteria
        task = (await authed_client.post("/api/tasks", json=body)).json()
        resp = await authed_client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})
        assert resp.status_code == 200
        return task, folder

    @pytest.mark.asyncio
    async def test_task_appears_in_review_flagged_as_having_no_repo(self, authed_client, tmp_path):
        task, _folder = await self._reviewable_task(authed_client, tmp_path, "plain1")
        tasks = (await authed_client.get("/api/review/tasks")).json()["tasks"]
        entry = next(t for t in tasks if t["id"] == task["id"])
        # has_repo is what lets the UI tell "nothing changed" apart from
        # "there was never anything to diff".
        assert entry["has_repo"] is False
        assert entry["file_count"] == 0

    @pytest.mark.asyncio
    async def test_listing_diffs_is_empty_rather_than_an_error(self, authed_client, tmp_path):
        task, _folder = await self._reviewable_task(authed_client, tmp_path, "plain2")
        resp = await authed_client.get("/api/review/diffs", params={"task_id": task["id"]})
        assert resp.status_code == 200
        assert resp.json() == {"has_repo": False, "branch": None, "diffs": []}

    @pytest.mark.asyncio
    async def test_approve_moves_the_task_to_done(self, authed_client, tmp_path):
        """The one that was outright impossible before."""
        task, _folder = await self._reviewable_task(authed_client, tmp_path, "plain3")

        resp = await authed_client.post("/api/review/approve", json={"task_id": task["id"]})
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["task_status"] == "done"

        assert (await authed_client.get(f"/api/tasks/{task['id']}")).json()["status"] == "done"

    @pytest.mark.asyncio
    async def test_approve_still_respects_the_acceptance_criteria_gate(
        self, authed_client, tmp_path,
    ):
        """Losing git must not mean losing the review gate — that check
        is task logic, and it's what makes this a real review."""
        task, _folder = await self._reviewable_task(
            authed_client, tmp_path, "plain4", criteria=["Must be proofread"],
        )
        resp = await authed_client.post("/api/review/approve", json={"task_id": task["id"]})
        assert resp.status_code == 200
        assert resp.json()["task_status"] == "review"
        assert resp.json()["done_error"]
        assert (await authed_client.get(f"/api/tasks/{task['id']}")).json()["status"] == "review"

    @pytest.mark.asyncio
    async def test_reject_sends_the_task_back_to_in_progress(
        self, authed_client, tmp_path, monkeypatch,
    ):
        # No live session to resume (none was ever started), so reject
        # falls through to starting a fresh one — which needs a
        # provider resolvable, same as the git-backed reject tests.
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        task, _folder = await self._reviewable_task(authed_client, tmp_path, "plain5")
        resp = await authed_client.post("/api/review/reject", json={
            "task_id": task["id"], "reason": "Needs a stronger conclusion",
        })
        assert resp.status_code == 200
        assert resp.json()["task_status"] == "in_progress"
        after = (await authed_client.get(f"/api/tasks/{task['id']}")).json()
        assert after["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_workspace_with_no_repository_at_all_is_reviewable(self, authed_client):
        """Not even a folder configured — still not a dead end."""
        await authed_client.post("/api/workspaces", json={"id": "bare", "name": "Bare"})
        task = (await authed_client.post(
            "/api/tasks", json={"title": "Think about it", "project": "bare"},
        )).json()
        await authed_client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})

        resp = await authed_client.post("/api/review/approve", json={"task_id": task["id"]})
        assert resp.status_code == 200
        assert resp.json()["task_status"] == "done"


class TestReviewSeesUntrackedFiles:
    """Found by running a real agent: it created one new file, and
    Review reported zero pending changes — while approve's `git add -A`
    committed it anyway. The reviewer approved something they were
    never shown."""

    @pytest.mark.asyncio
    async def test_a_new_file_from_the_agent_shows_up_in_review(self, authed_client, tmp_path):
        from agent_knots.gitutil import session_branch_name

        repo = tmp_path / "ws"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "README.md").write_text("seed\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

        await authed_client.post("/api/workspaces", json={
            "id": "untracked-ws", "name": "untracked-ws", "repository": str(repo),
        })
        task = (await authed_client.post(
            "/api/tasks", json={"title": "Make a thing", "project": "untracked-ws"},
        )).json()
        branch = session_branch_name(task["id"], "Make a thing", "")
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True)
        await authed_client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})

        # Exactly what an agent does: create a brand-new file, no commit.
        (repo / "greet.py").write_text("def greet(name):\n    return name\n")

        diffs = (await authed_client.get(
            "/api/review/diffs", params={"task_id": task["id"]},
        )).json()
        assert [d["file"] for d in diffs["diffs"]] == ["greet.py"]
        assert diffs["diffs"][0]["added"] == 2

        listed = (await authed_client.get("/api/review/tasks")).json()["tasks"]
        assert next(t for t in listed if t["id"] == task["id"])["file_count"] == 1

        text = (await authed_client.get(
            "/api/review/diff", params={"task_id": task["id"], "file": "greet.py"},
        )).json()["diff"]
        assert "+def greet(name):" in text

    @pytest.mark.asyncio
    async def test_ignored_files_stay_out_of_review(self, authed_client, tmp_path):
        """`git add -A` skips ignored files, so review must too —
        otherwise it lists junk that approve never commits."""
        from agent_knots.gitutil import session_branch_name

        repo = tmp_path / "ws2"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / ".gitignore").write_text("__pycache__/\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

        await authed_client.post("/api/workspaces", json={
            "id": "ignored-ws", "name": "ignored-ws", "repository": str(repo),
        })
        task = (await authed_client.post(
            "/api/tasks", json={"title": "Ignored", "project": "ignored-ws"},
        )).json()
        branch = session_branch_name(task["id"], "Ignored", "")
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True)
        await authed_client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})

        (repo / "__pycache__").mkdir()
        (repo / "__pycache__" / "x.pyc").write_bytes(b"\x00")

        diffs = (await authed_client.get(
            "/api/review/diffs", params={"task_id": task["id"]},
        )).json()
        assert diffs["diffs"] == []


class TestFeedbackMessage:
    """The prose sent back to the agent on reject."""

    def test_names_the_rejected_files_when_there_are_some(self):
        from agent_knots.cockpit.web.routes.review import _feedback_message

        msg = _feedback_message([], ["a.py", "b.py"], "Wrong approach")
        assert "a.py, b.py" in msg
        assert "Wrong approach" in msg

    def test_falls_back_to_task_level_wording_with_no_files(self):
        """Without this branch the agent got 'These files were
        rejected: .' — an empty list where it expects filenames."""
        from agent_knots.cockpit.web.routes.review import _feedback_message

        msg = _feedback_message([], [], "Missed the point")
        assert "These files were rejected" not in msg
        assert "Your work on this task was rejected" in msg
        assert "Missed the point" in msg

    def test_still_calls_out_already_approved_files(self):
        from agent_knots.cockpit.web.routes.review import _feedback_message

        msg = _feedback_message(["done.py"], [], "Try again")
        assert "done.py" in msg
        assert "Your work on this task was rejected" in msg


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


class TestVaultSharedInstance:
    """Regression guard: the web app used to build its own VaultStore
    independent of the one (if any) handed to SessionManager, so
    unlocking via the Settings UI never unlocked the store agent
    sessions actually read credentials from."""

    @pytest.mark.asyncio
    async def test_unlock_via_api_unlocks_the_session_managers_vault(self, agent_knots_home):
        from agent_knots.config import vault_dir
        from agent_knots.vault.store import VaultStore

        vault = VaultStore(vault_dir())
        mgr = SessionManager(agent_knots_home / "sessions", vault=vault)
        app = create_app(mgr)
        transport = ASGITransport(app=app)

        from agent_knots.config import cockpit_token_file
        from agent_knots.cockpit.web.auth import load_or_create_token
        token = load_or_create_token(cockpit_token_file())

        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=True,
        ) as c:
            resp = await c.post(
                "/api/vault/unlock", json={"passphrase": "hunter2"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200

        assert vault.unlocked is True


class TestVaultAPI:
    @pytest.mark.asyncio
    async def test_status_uninitialized(self, authed_client):
        resp = await authed_client.get("/api/vault/status")
        assert resp.json()["lock_state"] == "uninitialized"

    @pytest.mark.asyncio
    async def test_unlock_initializes_on_first_use(self, authed_client):
        resp = await authed_client.post("/api/vault/unlock", json={"passphrase": "hunter2"})
        assert resp.status_code == 200
        assert resp.json()["lock_state"] == "unlocked"

    @pytest.mark.asyncio
    async def test_credentials_require_unlock(self, authed_client):
        resp = await authed_client.get("/api/vault/credentials")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_add_list_delete_credential_never_leaks_value(self, authed_client):
        await authed_client.post("/api/vault/unlock", json={"passphrase": "hunter2"})

        resp = await authed_client.post("/api/vault/credentials", json={
            "id": "github", "description": "GH token", "tags": ["git"], "value": "ghp_secret123",
        })
        assert resp.status_code == 200

        resp = await authed_client.get("/api/vault/credentials")
        creds = resp.json()["credentials"]
        assert len(creds) == 1
        assert creds[0]["id"] == "github"
        assert "value" not in creds[0]
        assert "ghp_secret123" not in resp.text

        resp = await authed_client.delete("/api/vault/credentials/github")
        assert resp.status_code == 200
        assert (await authed_client.get("/api/vault/credentials")).json()["credentials"] == []

    @pytest.mark.asyncio
    async def test_add_credential_while_locked_400s(self, authed_client):
        await authed_client.post("/api/vault/unlock", json={"passphrase": "hunter2"})
        await authed_client.post("/api/vault/lock")
        resp = await authed_client.post("/api/vault/credentials", json={"id": "x", "value": "v"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_unlock_wrong_passphrase_400s(self, authed_client):
        await authed_client.post("/api/vault/unlock", json={"passphrase": "correct"})
        await authed_client.post("/api/vault/lock")
        resp = await authed_client.post("/api/vault/unlock", json={"passphrase": "wrong"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_audit_log_records_credential_add(self, authed_client):
        await authed_client.post("/api/vault/unlock", json={"passphrase": "hunter2"})
        await authed_client.post("/api/vault/credentials", json={"id": "github", "value": "secret"})
        resp = await authed_client.get("/api/vault/audit")
        entries = resp.json()["entries"]
        assert any(e["credential"] == "github" for e in entries)
        assert "secret" not in resp.text


class TestUsageAPI:
    @pytest.mark.asyncio
    async def test_empty_usage(self, authed_client):
        resp = await authed_client.get("/api/usage")
        data = resp.json()
        assert data["today"]["tokens"] == 0
        assert data["by_provider"] == []

    @pytest.mark.asyncio
    async def test_usage_reflects_recorded_session(self, authed_client, agent_knots_home):
        from agent_knots.config import usage_file
        from agent_knots.usage import UsageEntry, record

        record(usage_file(), UsageEntry(model="minimax-m2.7", task_id="T-1", tokens=500, cost_usd=0.05))
        resp = await authed_client.get("/api/usage")
        data = resp.json()
        assert data["today"]["tokens"] == 500
        assert data["by_provider"][0]["provider"] == "minimax"


class TestPoliciesAPI:
    @pytest.mark.asyncio
    async def test_list_defaults_all_disabled(self, authed_client):
        resp = await authed_client.get("/api/policies")
        policies = resp.json()["policies"]
        assert all(not p["enabled"] for p in policies)

    @pytest.mark.asyncio
    async def test_update_persists(self, authed_client):
        resp = await authed_client.patch("/api/policies/spend_cap", json={"enabled": True, "value": "2.50"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        assert resp.json()["value"] == "2.50"

    @pytest.mark.asyncio
    async def test_update_unknown_404s(self, authed_client):
        resp = await authed_client.patch("/api/policies/nonexistent", json={"enabled": True})
        assert resp.status_code == 404


class TestSpendCapEnforcement:
    @pytest.mark.asyncio
    async def test_session_blocked_once_cap_reached(self, authed_client, monkeypatch):
        from agent_knots.config import usage_file
        from agent_knots.usage import UsageEntry, record

        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")

        await authed_client.patch("/api/policies/spend_cap", json={"enabled": True, "value": "1.00"})
        record(usage_file(), UsageEntry(model="fake/model", tokens=1000, cost_usd=1.50))

        resp = await authed_client.post("/api/sessions", json={"prompt": ""})
        assert resp.status_code == 400
        assert "spend cap" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_disabled_cap_does_not_block(self, authed_client, monkeypatch):
        from agent_knots.config import usage_file
        from agent_knots.usage import UsageEntry, record

        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        record(usage_file(), UsageEntry(model="fake/model", tokens=1000, cost_usd=99.0))
        resp = await authed_client.post("/api/sessions", json={"prompt": ""})
        assert resp.status_code == 200


class TestMcpServersAPI:
    @pytest.mark.asyncio
    async def test_empty_by_default(self, authed_client):
        resp = await authed_client.get("/api/mcp")
        assert resp.json()["servers"] == []

    @pytest.mark.asyncio
    async def test_add_toggle_delete(self, authed_client):
        resp = await authed_client.post("/api/mcp", json={"name": "filesystem", "url": "stdio://fs"})
        assert resp.status_code == 200
        servers = resp.json()["servers"]
        assert servers[0]["enabled"] is False

        resp = await authed_client.post("/api/mcp/filesystem/toggle", json={"enabled": True})
        assert resp.json()["enabled"] is True

        resp = await authed_client.delete("/api/mcp/filesystem")
        assert resp.status_code == 200
        assert (await authed_client.get("/api/mcp")).json()["servers"] == []

    @pytest.mark.asyncio
    async def test_duplicate_name_409s(self, authed_client):
        await authed_client.post("/api/mcp", json={"name": "filesystem"})
        resp = await authed_client.post("/api/mcp", json={"name": "filesystem"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_get_single_server(self, authed_client):
        await authed_client.post("/api/mcp", json={"name": "filesystem", "url": "stdio://fs"})
        resp = await authed_client.get("/api/mcp/filesystem")
        assert resp.status_code == 200
        assert resp.json()["name"] == "filesystem"
        assert resp.json()["url"] == "stdio://fs"

    @pytest.mark.asyncio
    async def test_get_single_server_not_found_404s(self, authed_client):
        resp = await authed_client.get("/api/mcp/nonexistent")
        assert resp.status_code == 404


class TestProvidersAndIntegrationsAPI:
    @pytest.mark.asyncio
    async def test_no_providers_by_default(self, authed_client):
        resp = await authed_client.get("/api/settings")
        assert resp.json()["providers"] == []

    @pytest.mark.asyncio
    async def test_add_provider_never_returns_raw_key(self, authed_client):
        resp = await authed_client.post("/api/settings/providers", json={
            "name": "minimax", "model": "minimax-m2.7", "api_key": "sk-real-secret", "base_url": "https://api.minimax.io/v1",
        })
        assert resp.status_code == 200
        assert "sk-real-secret" not in resp.text
        providers = resp.json()["providers"]
        assert providers[0]["key_set"] is True

    @pytest.mark.asyncio
    async def test_duplicate_provider_name_409s(self, authed_client):
        await authed_client.post("/api/settings/providers", json={"name": "minimax", "api_key": "k"})
        resp = await authed_client.post("/api/settings/providers", json={"name": "minimax", "api_key": "k2"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_set_default_updates_agent_settings_and_resolve_provider(self, authed_client):
        await authed_client.post("/api/settings/providers", json={
            "name": "minimax", "model": "minimax-m2.7", "api_key": "sk-real", "base_url": "https://api.minimax.io/v1",
        })
        resp = await authed_client.post("/api/settings/providers/minimax/default")
        assert resp.status_code == 200

        settings_resp = await authed_client.get("/api/settings")
        data = settings_resp.json()
        assert data["agent"]["default_model"] == "minimax-m2.7"
        assert data["default_provider"] == "minimax"
        assert data["providers"][0]["is_default"] is True

    @pytest.mark.asyncio
    async def test_delete_unknown_provider_404s(self, authed_client):
        resp = await authed_client.delete("/api/settings/providers/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_save_integrations_persists(self, authed_client):
        resp = await authed_client.put("/api/integrations", json={"github_pr_on_review": True, "phone_push": True})
        assert resp.status_code == 200
        settings_resp = await authed_client.get("/api/settings")
        integrations = settings_resp.json()["integrations"]
        assert integrations["github_pr_on_review"] is True
        assert integrations["phone_push"] is True


class TestSpaFallbackServesRootStaticFiles:
    """Vite copies frontend/public/* to the root of dist/ (favicon.svg,
    favicon.ico, site.webmanifest, etc.), not into dist/assets/ — only
    /assets was ever mounted as StaticFiles, so a request for one of
    these root-level files used to fall through to the SPA fallback
    and get the HTML shell back instead of the real file (the browser
    then silently fails to render it as a favicon/icon/manifest)."""

    @pytest.fixture
    async def static_client(self, session_manager, auth_token, tmp_path):
        static_dir = tmp_path / "dist"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html>spa shell</html>")
        (static_dir / "favicon.svg").write_text("<svg>real favicon</svg>")
        secret_outside = tmp_path / "secret.txt"
        secret_outside.write_text("should never be served")

        app = create_app(session_manager, static_dir=static_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
            c.cookies.set("agent-knots-session", auth_token)
            yield c

    @pytest.mark.asyncio
    async def test_root_level_static_file_served_directly(self, static_client):
        resp = await static_client.get("/favicon.svg")
        assert resp.status_code == 200
        assert resp.text == "<svg>real favicon</svg>"
        assert "spa shell" not in resp.text

    @pytest.mark.asyncio
    async def test_unknown_path_still_falls_back_to_spa_shell(self, static_client):
        resp = await static_client.get("/tasks/T-123")
        assert resp.status_code == 200
        assert "spa shell" in resp.text

    @pytest.mark.asyncio
    async def test_path_traversal_does_not_escape_static_dir(self, static_client):
        resp = await static_client.get("/../secret.txt")
        assert "should never be served" not in resp.text


class TestWastebinAPI:
    @pytest.mark.asyncio
    async def test_empty_wastebin(self, authed_client):
        resp = await authed_client.get("/api/wastebin")
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    @pytest.mark.asyncio
    async def test_stopped_session_appears_as_a_tombstone(
        self, authed_client, session_manager, monkeypatch,
    ):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        created = await authed_client.post("/api/tasks", json={"title": "Wastebin test"})
        task_id = created.json()["id"]
        session = await authed_client.post(
            "/api/sessions", json={"prompt": "", "mode": "agent", "task_id": task_id},
        )
        session_id = session.json()["id"]

        await authed_client.delete(f"/api/agent/{session_id}")

        resp = await authed_client.get("/api/wastebin")
        entries = resp.json()["entries"]
        assert any(e["session_id"] == session_id for e in entries)
        entry = next(e for e in entries if e["session_id"] == session_id)
        assert entry["task_id"] == task_id
        assert entry["task_title"] == "Wastebin test"

    @pytest.mark.asyncio
    async def test_delete_removes_the_entry(self, authed_client, session_manager, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        session = await authed_client.post("/api/sessions", json={"prompt": "", "mode": "agent"})
        session_id = session.json()["id"]
        await authed_client.delete(f"/api/agent/{session_id}")

        resp = await authed_client.delete(f"/api/wastebin/{session_id}")
        assert resp.status_code == 200

        entries = (await authed_client.get("/api/wastebin")).json()["entries"]
        assert not any(e["session_id"] == session_id for e in entries)

    @pytest.mark.asyncio
    async def test_delete_unknown_entry_404s(self, authed_client):
        resp = await authed_client.delete("/api/wastebin/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_force_deletes_a_surviving_branch(
        self, authed_client, session_manager, tmp_path, monkeypatch,
    ):
        import subprocess

        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

        await authed_client.post(
            "/api/workspaces", json={"id": "wb-repo", "name": "WB", "repository": str(repo)},
        )
        created = await authed_client.post(
            "/api/tasks", json={"title": "Branch to delete", "project": "wb-repo"},
        )
        task_id = created.json()["id"]
        session = await authed_client.post(
            "/api/sessions",
            json={"prompt": "", "mode": "agent", "task_id": task_id, "project_id": "wb-repo"},
        )
        session_id = session.json()["id"]
        session_obj = session_manager.get(session_id)
        branch = session_obj.branch
        assert branch

        # Make the working tree dirty so the branch survives stop()
        # (see the dirty-tree fix — otherwise it'd already be gone).
        (repo / "a.txt").write_text("one\ntwo\n")

        await authed_client.delete(f"/api/agent/{session_id}")
        result = subprocess.run(
            ["git", "branch", "--list", branch], cwd=repo, capture_output=True, text=True,
        )
        assert branch in result.stdout  # survived stop() — dirty tree

        await authed_client.delete(f"/api/wastebin/{session_id}")
        result = subprocess.run(
            ["git", "branch", "--list", branch], cwd=repo, capture_output=True, text=True,
        )
        assert branch not in result.stdout  # force-deleted by the wastebin

    @pytest.mark.asyncio
    async def test_retention_zero_never_purges(self, authed_client, session_manager, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_API_KEY", "sk-fake")
        monkeypatch.setenv("AGENT_KNOTS_MODEL", "fake/model")
        monkeypatch.setenv("AGENT_KNOTS_BASE_URL", "http://fake-does-not-exist.invalid")

        await authed_client.put("/api/settings", json={"wastebin_retention_days": 0})
        session = await authed_client.post("/api/sessions", json={"prompt": "", "mode": "agent"})
        session_id = session.json()["id"]
        await authed_client.delete(f"/api/agent/{session_id}")

        entries = (await authed_client.get("/api/wastebin")).json()["entries"]
        assert any(e["session_id"] == session_id for e in entries)

class TestPlaygroundSeeding:
    """Cloning a repo that ships a playground manifest.

    The playground is a real half-built demo project: someone clones it
    and arrives with the genuine tasks that built it, some done, one
    waiting on review, some never started."""

    def _demo_tasks(self):
        from agent_knots.task.models import Priority, ProgressEntry, Task, TaskStatus

        specs = [
            ("T-2026-01-01-000001-aaaa-demo", "Scaffold the Vite app", TaskStatus.DONE),
            ("T-2026-01-01-000002-bbbb-demo", "Add the contrast checker", TaskStatus.REVIEW),
            ("T-2026-01-01-000003-cccc-demo", "Shareable palette URLs", TaskStatus.DRAFT),
        ]
        out = []
        for tid, title, status in specs:
            t = Task(id=tid, title=title, status=status, project="built-here",
                     priority=Priority.MEDIUM)
            t.progress.append(ProgressEntry(entry=f"[editor_tool] did {title}"))
            out.append(t)
        return out

    def _demo_repo(self, tmp_path, name="demo", tasks=None):
        """A git repo shipping a playground manifest, as the public
        demo repo would."""
        from agent_knots.playground import write_manifest

        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "README.md").write_text("# demo\n")
        write_manifest(repo, self._demo_tasks() if tasks is None else tasks)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
        return repo

    def _plain_repo(self, tmp_path, name):
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "f.txt").write_text("x\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
        return repo

    @pytest.mark.asyncio
    async def test_clone_seeds_the_shipped_tasks(self, authed_client, tmp_path):
        repo = self._demo_repo(tmp_path)
        resp = await authed_client.post("/api/workspaces", json={
            "id": "pg", "name": "Playground", "repository": str(repo),
            "managed": True, "seed_tasks": True,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["seeded_tasks"] == 3

        listed = (await authed_client.get("/api/tasks", params={"project": "pg"})).json()["tasks"]
        assert {t["status"] for t in listed} == {"done", "review", "draft"}

    @pytest.mark.asyncio
    async def test_seeding_is_opt_in(self, authed_client, tmp_path):
        """A repo you cloned should not be able to put things on your
        board unasked."""
        repo = self._demo_repo(tmp_path)
        resp = await authed_client.post("/api/workspaces", json={
            "id": "quiet", "name": "Quiet", "repository": str(repo), "managed": True,
        })
        assert resp.json()["seeded_tasks"] == 0
        listed = (await authed_client.get("/api/tasks", params={"project": "quiet"})).json()
        assert listed["tasks"] == []

    @pytest.mark.asyncio
    async def test_repo_without_a_manifest_is_not_an_error(self, authed_client, tmp_path):
        """Every ordinary repo is this case — seeding just finds
        nothing to do."""
        repo = self._plain_repo(tmp_path, "plain")
        resp = await authed_client.post("/api/workspaces", json={
            "id": "plain", "name": "Plain", "repository": str(repo),
            "managed": True, "seed_tasks": True,
        })
        assert resp.status_code == 200
        assert resp.json()["seeded_tasks"] == 0

    @pytest.mark.asyncio
    async def test_reseeding_does_not_duplicate(self, authed_client, tmp_path):
        """Ids are preserved by design, so a second import of the same
        repo must skip rather than clobber — whatever is on the board
        may already have real progress on it."""
        repo = self._demo_repo(tmp_path)
        for ws in ("first", "second"):
            await authed_client.post("/api/workspaces", json={
                "id": ws, "name": ws, "repository": str(repo),
                "managed": True, "seed_tasks": True,
            })
        everything = (await authed_client.get("/api/tasks")).json()["tasks"]
        assert len([t for t in everything if t["id"].startswith("T-2026-01-01")]) == 3

    @pytest.mark.asyncio
    async def test_a_broken_manifest_fails_loudly(self, authed_client, tmp_path):
        """The caller explicitly asked to seed; a silently empty board
        would be baffling."""
        from agent_knots.playground import manifest_path
        from agent_knots.yamlfile import atomic_write_yaml

        repo = self._plain_repo(tmp_path, "bad")
        path = manifest_path(repo)
        path.parent.mkdir(parents=True)
        atomic_write_yaml(path, {"version": 99, "tasks": []})
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "manifest"], cwd=repo, check=True)

        resp = await authed_client.post("/api/workspaces", json={
            "id": "bad", "name": "Bad", "repository": str(repo),
            "managed": True, "seed_tasks": True,
        })
        assert resp.status_code == 400
        assert "manifest" in resp.json()["detail"].lower()
