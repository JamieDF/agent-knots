"""MCP server registry API (config-only — no real client wiring)."""

from fastapi import APIRouter, HTTPException

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import AddMcpServerRequest, ToggleRequest
from agent_knots.config import mcp_servers_file
from agent_knots.mcp_servers import McpServer, McpServerStore


def _mcp_to_response(s) -> dict:
    return {
        "name": s.name, "url": s.url, "enabled": s.enabled,
        "tool_count": s.tool_count, "created_at": s.created_at,
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/mcp")
    async def list_mcp_servers():
        return {"servers": [_mcp_to_response(s) for s in McpServerStore(mcp_servers_file()).list()]}

    @router.get("/api/mcp/{name}")
    async def get_mcp_server(name: str):
        """Get a single MCP server's detail."""
        server = McpServerStore(mcp_servers_file()).get(name)
        if server is None:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return _mcp_to_response(server)

    @router.post("/api/mcp")
    @raises_as(409)
    async def add_mcp_server(body: AddMcpServerRequest):
        store = McpServerStore(mcp_servers_file())
        store.add(McpServer(name=body.name, url=body.url))
        return {"servers": [_mcp_to_response(s) for s in store.list()]}

    @router.post("/api/mcp/{name}/toggle")
    @raises_as(404)
    async def toggle_mcp_server(name: str, body: ToggleRequest):
        store = McpServerStore(mcp_servers_file())
        server = store.toggle(name, body.enabled)
        return _mcp_to_response(server)

    @router.delete("/api/mcp/{name}")
    @raises_as(404)
    async def delete_mcp_server(name: str):
        store = McpServerStore(mcp_servers_file())
        store.remove(name)
        return {"status": "ok"}

    return router
