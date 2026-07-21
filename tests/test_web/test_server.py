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

    @pytest.mark.asyncio
    async def test_checkpoint_unknown_agent_404s(self, authed_client):
        resp = await authed_client.post("/api/agent/nonexistent/checkpoint", json={"label": "x"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_revert_unknown_agent_404s(self, authed_client):
        resp = await authed_client.post("/api/agent/nonexistent/revert", json={"label": "x"})
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
        open to in_progress should auto-start a session — the trigger
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
    async def test_disabled_role_does_not_fire(self, authed_client, session_manager):
        """Roles are disabled by default — no trigger should fire."""
        created = await authed_client.post("/api/tasks", json={"title": "No trigger test"})
        task_id = created.json()["id"]

        before = len(session_manager.active)
        await authed_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
        await asyncio.sleep(0.1)
        assert len(session_manager.active) == before


class TestReviewAPI:
    @pytest.mark.asyncio
    async def test_list_diffs_empty_when_no_workspaces(self, authed_client):
        resp = await authed_client.get("/api/review/diffs")
        assert resp.status_code == 200
        assert resp.json()["diffs"] == []

    @pytest.mark.asyncio
    async def test_list_diffs_skips_workspace_without_git_repo(self, authed_client, tmp_path):
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        await authed_client.post("/api/workspaces", json={"id": "w1", "name": "W1", "repository": str(non_repo)})
        resp = await authed_client.get("/api/review/diffs")
        assert resp.json()["diffs"] == []

    @pytest.mark.asyncio
    async def test_list_diffs_from_real_git_repo(self, authed_client, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\ntwo\n")

        await authed_client.post("/api/workspaces", json={"id": "w2", "name": "W2", "repository": str(repo)})
        resp = await authed_client.get("/api/review/diffs")
        diffs = resp.json()["diffs"]
        assert len(diffs) == 1
        assert diffs[0]["file"] == "a.txt"
        assert diffs[0]["added"] == 1

    @pytest.mark.asyncio
    async def test_approve_commits_the_file(self, authed_client, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\ntwo\n")

        await authed_client.post("/api/workspaces", json={"id": "w3", "name": "W3", "repository": str(repo)})
        resp = await authed_client.post("/api/review/approve", json={"workspace": "w3", "file": "a.txt"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "committed"

        # No longer a pending diff, and git log shows the new commit.
        diffs = (await authed_client.get("/api/review/diffs")).json()["diffs"]
        assert diffs == []
        log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True)
        assert log.stdout.count("\n") == 2

    @pytest.mark.asyncio
    async def test_reject_does_not_discard_changes(self, authed_client, tmp_path):
        """Reject must never run a destructive git operation — it only
        acknowledges. Confirmed by checking the file is untouched."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        (repo / "a.txt").write_text("one\ntwo\n")

        await authed_client.post("/api/workspaces", json={"id": "w4", "name": "W4", "repository": str(repo)})
        resp = await authed_client.post("/api/review/reject", json={"workspace": "w4", "file": "a.txt"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        # The uncommitted edit must still be there — reject didn't discard it.
        assert (repo / "a.txt").read_text() == "one\ntwo\n"
        diffs = (await authed_client.get("/api/review/diffs")).json()["diffs"]
        assert len(diffs) == 1

    @pytest.mark.asyncio
    async def test_approve_unknown_workspace_404s(self, authed_client):
        resp = await authed_client.post("/api/review/approve", json={"workspace": "nonexistent"})
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
