"""Workflows API: board stages and default agent roles."""

from fastapi import APIRouter

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import ToggleRequest, UpdateRoleRequest
from agent_knots.config import roles_file, stages_file
from agent_knots.workflows.store import RolesStore, StagesStore


def _role_to_response(role) -> dict:
    return {
        "key": role.key, "name": role.name, "icon": role.icon, "description": role.description,
        "model": role.model, "trigger": role.trigger.value, "prompt": role.prompt,
        "tools": role.tools, "enabled": role.enabled,
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/stages")
    async def list_stages():
        return {"stages": [
            {"key": s.key, "label": s.label, "statuses": s.statuses, "enabled": s.enabled, "required": s.required}
            for s in StagesStore(stages_file()).list()
        ]}

    @router.post("/api/stages/{key}/toggle")
    @raises_as(400)
    async def toggle_stage(key: str, body: ToggleRequest):
        stages = StagesStore(stages_file()).toggle(key, body.enabled)
        return {"stages": [
            {"key": s.key, "label": s.label, "statuses": s.statuses, "enabled": s.enabled, "required": s.required}
            for s in stages
        ]}

    @router.get("/api/roles")
    async def list_roles():
        return {"roles": [_role_to_response(r) for r in RolesStore(roles_file()).list()]}

    @router.patch("/api/roles/{key}")
    @raises_as(404)
    async def update_role(key: str, body: UpdateRoleRequest):
        role = RolesStore(roles_file()).update(key, **body.model_dump(exclude_unset=True))
        return _role_to_response(role)

    return router
