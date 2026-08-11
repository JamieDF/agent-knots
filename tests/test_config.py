"""Tests for path resolution in config.py.

Mostly about workspaces_root(), which is the one path that deliberately
escapes AGENT_KNOTS_HOME and so needs its precedence pinned down.
"""

from pathlib import Path

import pytest

from agent_knots.config import session_workdir, workspaces_root


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Neither variable set, so each test opts into exactly the one it
    is about. Without this the developer's own environment leaks in."""
    monkeypatch.delenv("AGENT_KNOTS_HOME", raising=False)
    monkeypatch.delenv("AGENT_KNOTS_WORKSPACES_ROOT", raising=False)


class TestWorkspacesRoot:
    def test_explicit_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_WORKSPACES_ROOT", str(tmp_path / "elsewhere"))
        monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path / "home"))
        assert workspaces_root() == tmp_path / "elsewhere"

    def test_settings_value_beats_the_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path / "home"))
        from agent_knots import settings as settings_mod

        s = settings_mod.load()
        s.workspaces_root = str(tmp_path / "configured")
        settings_mod.save(s)

        assert workspaces_root() == tmp_path / "configured"

    def test_follows_agent_knots_home_when_it_is_set(self, tmp_path, monkeypatch):
        """The rule that keeps every existing test fixture isolating.
        Fixtures point AGENT_KNOTS_HOME at a tmp_path; since the
        workspaces root lives outside _home(), without this it would
        escape the sandbox and write to the real ~/agent-knots."""
        monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path / "home"))
        assert workspaces_root() == tmp_path / "home" / "workspaces"

    def test_defaults_to_a_visible_folder_in_the_real_home(self, monkeypatch, tmp_path):
        """What an actual user gets: not buried in the ~/.agent-knots
        dotfolder, because it holds their code rather than our state."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert workspaces_root() == tmp_path / "agent-knots" / "workspaces"

    def test_creates_the_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_KNOTS_WORKSPACES_ROOT", str(tmp_path / "made"))
        assert workspaces_root().is_dir()


class TestSessionWorkdir:
    def test_still_lives_under_agent_knots_home(self, tmp_path, monkeypatch):
        """The safety net for a session with no workspace at all stays
        internal state — managed workspaces moving out from under
        _home() must not drag this with them."""
        monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
        assert session_workdir("sess-1") == tmp_path / "workdirs" / "sess-1"
