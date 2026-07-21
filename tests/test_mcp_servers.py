"""Tests for the MCP server registry store."""

import tempfile
from pathlib import Path

import pytest

from agent_knots.mcp_servers import McpServer, McpServerStore


@pytest.fixture
def store_path():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "mcp_servers.yaml"


class TestMcpServerStore:
    def test_list_empty_when_no_file(self, store_path):
        store = McpServerStore(store_path)
        assert store.list() == []

    def test_add_and_list(self, store_path):
        store = McpServerStore(store_path)
        store.add(McpServer(name="filesystem", url="stdio://fs"))
        servers = store.list()
        assert len(servers) == 1
        assert servers[0].name == "filesystem"
        assert servers[0].enabled is False

    def test_add_duplicate_raises(self, store_path):
        store = McpServerStore(store_path)
        store.add(McpServer(name="filesystem"))
        with pytest.raises(ValueError, match="already exists"):
            store.add(McpServer(name="filesystem"))

    def test_toggle_persists(self, store_path):
        store = McpServerStore(store_path)
        store.add(McpServer(name="filesystem"))
        store.toggle("filesystem", True)
        assert store.list()[0].enabled is True

    def test_toggle_unknown_raises(self, store_path):
        store = McpServerStore(store_path)
        with pytest.raises(ValueError, match="not found"):
            store.toggle("nonexistent", True)

    def test_remove(self, store_path):
        store = McpServerStore(store_path)
        store.add(McpServer(name="filesystem"))
        store.remove("filesystem")
        assert store.list() == []

    def test_remove_unknown_raises(self, store_path):
        store = McpServerStore(store_path)
        with pytest.raises(ValueError, match="not found"):
            store.remove("nonexistent")
