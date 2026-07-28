"""MCP server registry — config-only in this version. Add/list/toggle/
remove a server entry; there's no real MCP client wiring yet. Unlike the
fixed-cardinality Stages/Roles lists, this one grows with add/remove,
so it's a plain YAML list store rather than a whole-list-only one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class McpServer:
    name: str
    url: str = ""
    enabled: bool = False
    tool_count: int = 0
    created_at: float = field(default_factory=time.time)


class McpServerStore:
    """YAML file-backed store for the MCP server registry."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def list(self) -> list[McpServer]:
        if not self._path.exists():
            return []
        try:
            data = yaml.safe_load(self._path.read_text())
            if not isinstance(data, list):
                return []
            return [self._from_dict(d) for d in data]
        except (yaml.YAMLError, OSError, KeyError):
            return []

    def get(self, name: str) -> McpServer | None:
        return next((s for s in self.list() if s.name == name), None)

    def add(self, server: McpServer) -> None:
        servers = self.list()
        if any(s.name == server.name for s in servers):
            raise ValueError(f"MCP server {server.name!r} already exists")
        servers.append(server)
        self._save(servers)

    def remove(self, name: str) -> None:
        servers = self.list()
        remaining = [s for s in servers if s.name != name]
        if len(remaining) == len(servers):
            raise ValueError(f"MCP server {name!r} not found")
        self._save(remaining)

    def toggle(self, name: str, enabled: bool) -> McpServer:
        servers = self.list()
        server = next((s for s in servers if s.name == name), None)
        if server is None:
            raise ValueError(f"MCP server {name!r} not found")
        server.enabled = enabled
        self._save(servers)
        return server

    def _save(self, servers: list[McpServer]) -> None:
        data = [self._to_dict(s) for s in servers]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        tmp.rename(self._path)

    @staticmethod
    def _to_dict(s: McpServer) -> dict[str, Any]:
        return {
            "name": s.name, "url": s.url, "enabled": s.enabled,
            "tool_count": s.tool_count, "created_at": s.created_at,
        }

    @staticmethod
    def _from_dict(d: dict[str, Any]) -> McpServer:
        return McpServer(
            name=d["name"], url=d.get("url", ""), enabled=d.get("enabled", False),
            tool_count=d.get("tool_count", 0), created_at=d.get("created_at", 0.0),
        )
