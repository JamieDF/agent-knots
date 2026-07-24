"""Tool registry API (built-in + custom shell-command tools)."""

from fastapi import APIRouter, HTTPException

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import CreateToolRequest, UpdateToolRequest
from agent_knots.tools.registry import CustomTool, ToolRegistry


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/tools")
    async def list_tools():
        """List all tools (built-in + custom)."""
        registry = ToolRegistry()
        tools = registry.list_all()
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "builtin": t.builtin,
                    "enabled": t.enabled,
                    "created_at": t.created_at,
                }
                for t in tools
            ]
        }

    @router.get("/api/tools/{name}")
    async def get_tool(name: str):
        """Get a custom tool's full definition."""
        registry = ToolRegistry()
        ct = registry.get_custom(name)
        if ct is None:
            raise HTTPException(status_code=404, detail="Custom tool not found")
        return {
            "name": ct.name,
            "description": ct.description,
            "command": ct.command,
            "parameters": ct.parameters,
            "enabled": ct.enabled,
            "created_at": ct.created_at,
        }

    @router.post("/api/tools")
    @raises_as(409)
    async def create_tool(body: CreateToolRequest):
        """Create a new custom tool."""
        registry = ToolRegistry()
        ct = CustomTool(
            name=body.name,
            description=body.description,
            command=body.command,
            parameters=body.parameters,
        )
        registry.add_custom(ct)
        return {"status": "ok", "name": ct.name}

    @router.patch("/api/tools/{name}")
    async def update_tool(name: str, body: UpdateToolRequest):
        """Update a custom tool."""
        registry = ToolRegistry()
        ct = registry.get_custom(name)
        if ct is None:
            raise HTTPException(status_code=404, detail="Custom tool not found")
        if body.description is not None:
            ct.description = body.description
        if body.command is not None:
            ct.command = body.command
        if body.parameters is not None:
            ct.parameters = body.parameters
        registry.update_custom(ct)
        return {"status": "ok"}

    @router.delete("/api/tools/{name}")
    @raises_as(404)
    async def delete_tool(name: str):
        """Delete a custom tool."""
        registry = ToolRegistry()
        registry.delete_custom(name)
        return {"status": "ok"}

    @router.post("/api/tools/{name}/toggle")
    @raises_as(404)
    async def toggle_tool(name: str):
        """Toggle a tool's enabled state (built-in or custom)."""
        tool = ToolRegistry().toggle(name)
        return {"enabled": tool.enabled}

    return router
