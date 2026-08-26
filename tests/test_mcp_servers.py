"""Tests for the MCP server registry store."""

import pytest

from agent_knots.mcp_servers import McpServer, McpServerStore
from agent_knots.storage import reset_stores


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    reset_stores()
    yield
    reset_stores()


class TestMcpServerStore:
    def test_list_empty_when_unset(self):
        store = McpServerStore()
        assert store.list() == []

    def test_add_and_list(self):
        store = McpServerStore()
        store.add(McpServer(name="filesystem", url="stdio://fs"))
        servers = store.list()
        assert len(servers) == 1
        assert servers[0].name == "filesystem"
        assert servers[0].enabled is False

    def test_add_duplicate_raises(self):
        store = McpServerStore()
        store.add(McpServer(name="filesystem"))
        with pytest.raises(ValueError, match="already exists"):
            store.add(McpServer(name="filesystem"))

    def test_toggle_persists(self):
        store = McpServerStore()
        store.add(McpServer(name="filesystem"))
        store.toggle("filesystem", True)
        assert store.list()[0].enabled is True

    def test_toggle_unknown_raises(self):
        store = McpServerStore()
        with pytest.raises(ValueError, match="not found"):
            store.toggle("nonexistent", True)

    def test_remove(self):
        store = McpServerStore()
        store.add(McpServer(name="filesystem"))
        store.remove("filesystem")
        assert store.list() == []

    def test_remove_unknown_raises(self):
        store = McpServerStore()
        with pytest.raises(ValueError, match="not found"):
            store.remove("nonexistent")
