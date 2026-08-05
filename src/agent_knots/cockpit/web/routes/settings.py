"""Settings, provider profiles, integrations, usage, and policy routes.

Grouped together (rather than one router per Pydantic model) since
they're all app-wide configuration surfaces read/written by the same
Settings screen, unlike task/agent/vault which are separate domains
with their own stores.
"""

from fastapi import APIRouter, HTTPException

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import (
    AddProviderRequest, SaveIntegrationsRequest, SaveSettingsRequest, UpdatePolicyRequest,
)
from agent_knots.config import policies_file, usage_file
from agent_knots import provider as provider_module
from agent_knots import settings
from agent_knots import usage as usage_module
from agent_knots.policies.store import PolicyStore


def _providers_to_response(s: "settings.Settings") -> list[dict]:
    """Saved provider profiles, plus (if none are saved yet but a legacy
    single-provider config already exists) a synthetic 'default' entry
    so existing installs don't see an empty list. Never returns a raw
    api_key — only whether one is set."""
    if s.providers:
        return [
            {
                "name": p.name, "model": p.model, "base_url": p.base_url,
                "key_set": bool(p.api_key), "is_default": p.name == s.default_provider,
            }
            for p in s.providers
        ]
    if s.agent.api_key:
        return [{
            "name": "default", "model": s.agent.default_model, "base_url": s.agent.base_url,
            "key_set": True, "is_default": True,
        }]
    return []


def _policy_to_response(p) -> dict:
    return {
        "key": p.key, "label": p.label, "description": p.description,
        "enabled": p.enabled, "value": p.value, "enforced": p.enforced,
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/settings")
    async def get_settings():
        """Return current settings (API key masked).

        "configured" reflects whether a session could actually be started
        right now — CLI flags aren't relevant here, but env vars are, so
        this checks the same resolve_provider() precedence SessionManager
        uses rather than only the settings file. Otherwise a GUI user who
        configured via AGENT_KNOTS_API_KEY would get stuck behind the
        setup wizard even though sessions would actually work.
        """
        s = settings.load()
        return {
            "configured": provider_module.resolve_provider().is_configured,
            "agent": {
                "default_model": s.agent.default_model,
                "api_key": settings.mask_key(s.agent.api_key),
                "base_url": s.agent.base_url,
                "default_mode": s.agent.default_mode,
                "runtime": s.agent.runtime,
            },
            "providers": _providers_to_response(s),
            "default_provider": s.default_provider,
            "integrations": {
                "github_pr_on_review": s.integrations.github_pr_on_review,
                "phone_push": s.integrations.phone_push,
            },
            "wastebin": {
                "retention_days": s.wastebin.retention_days,
            },
        }

    @router.put("/api/settings")
    async def save_settings(body: SaveSettingsRequest):
        """Save settings. Empty fields preserve existing values."""
        s = settings.load()

        if body.default_model:
            s.agent.default_model = body.default_model
        if body.base_url:
            s.agent.base_url = body.base_url
        if body.default_mode:
            s.agent.default_mode = body.default_mode
        if body.runtime:
            s.agent.runtime = body.runtime

        # Only update API key if a real value was provided (not masked).
        if body.api_key and "..." not in body.api_key and not body.api_key.startswith("****"):
            s.agent.api_key = body.api_key

        if body.wastebin_retention_days is not None:
            s.wastebin.retention_days = body.wastebin_retention_days

        settings.save(s)
        return {"status": "ok", "configured": provider_module.resolve_provider().is_configured}

    @router.post("/api/settings/providers")
    async def add_provider(body: AddProviderRequest):
        """Save a named provider profile. Doesn't touch resolve_provider()'s
        active config — only 'Set default' below does that."""
        s = settings.load()
        if any(p.name == body.name for p in s.providers):
            raise HTTPException(status_code=409, detail=f"Provider {body.name!r} already exists")
        s.providers.append(settings.ProviderProfile(
            name=body.name, model=body.model, api_key=body.api_key, base_url=body.base_url,
        ))
        settings.save(s)
        return {"providers": _providers_to_response(s)}

    @router.delete("/api/settings/providers/{name}")
    async def delete_provider(name: str):
        s = settings.load()
        remaining = [p for p in s.providers if p.name != name]
        if len(remaining) == len(s.providers):
            raise HTTPException(status_code=404, detail="Provider not found")
        s.providers = remaining
        if s.default_provider == name:
            s.default_provider = ""
        settings.save(s)
        return {"providers": _providers_to_response(s)}

    @router.patch("/api/settings/providers/{name}")
    @raises_as(404)
    async def update_provider(name: str, body: dict):
        """Update a saved provider profile's fields (model, api_key,
        base_url). Used by the model browser's "Use" button to set the
        active model without re-entering the key."""
        s = settings.load()
        profile = next((p for p in s.providers if p.name == name), None)
        if profile is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        if "model" in body:
            profile.model = body["model"]
        if "base_url" in body:
            profile.base_url = body["base_url"]
        # Only update the key if a real value is provided (not masked).
        if "api_key" in body and body["api_key"] and not body["api_key"].endswith("..."):
            profile.api_key = body["api_key"]
        # If this provider is the active default, sync the agent config
        # so the change takes effect immediately.
        if s.default_provider == name:
            s.agent.default_model = profile.model
            s.agent.base_url = profile.base_url
            if "api_key" in body and body["api_key"] and not body["api_key"].endswith("..."):
                s.agent.api_key = profile.api_key
        settings.save(s)
        return {"providers": _providers_to_response(s)}

    @router.post("/api/settings/providers/{name}/default")
    async def set_default_provider(name: str):
        """Make a saved provider profile the active one — copies its
        model/key/url into `agent`, which is what resolve_provider()
        actually reads. Never touches env-var precedence."""
        s = settings.load()
        profile = next((p for p in s.providers if p.name == name), None)
        if profile is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        s.agent.default_model = profile.model
        s.agent.api_key = profile.api_key
        s.agent.base_url = profile.base_url
        s.default_provider = name
        settings.save(s)
        return {"status": "ok", "default_provider": name}

    @router.get("/api/settings/providers/{name}/models")
    @raises_as(400)
    async def list_provider_models(name: str):
        """Query a saved provider's API for its available models via the
        OpenAI-compatible GET /v1/models endpoint. Bypasses Strands (which
        has no model-listing surface) and constructs an openai client
        directly from the profile's key/url.

        Will fail cleanly on providers that aren't OpenAI-compatible
        (e.g. Anthropic's native API) — surfaced as a 400 with a message
        the frontend shows to the user.
        """
        s = settings.load()
        profile = next((p for p in s.providers if p.name == name), None)
        if profile is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        if not profile.api_key:
            raise HTTPException(status_code=400, detail="Provider has no API key set")

        from openai import AsyncOpenAI

        base_url = profile.base_url or "https://api.openai.com/v1"
        client = AsyncOpenAI(api_key=profile.api_key, base_url=base_url)
        try:
            response = await client.models.list()
            return {"models": [{"id": m.id, "owned_by": m.owned_by} for m in response.data]}
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not list models from {name}: {e}",
            )

    @router.put("/api/integrations")
    async def save_integrations(body: SaveIntegrationsRequest):
        s = settings.load()
        if body.github_pr_on_review is not None:
            s.integrations.github_pr_on_review = body.github_pr_on_review
        if body.phone_push is not None:
            s.integrations.phone_push = body.phone_push
        settings.save(s)
        return {"status": "ok"}

    @router.get("/api/usage")
    async def get_usage():
        return usage_module.summary(usage_file())

    @router.get("/api/policies")
    async def list_policies():
        return {"policies": [_policy_to_response(p) for p in PolicyStore(policies_file()).list()]}

    @router.patch("/api/policies/{key}")
    @raises_as(404)
    async def update_policy(key: str, body: UpdatePolicyRequest):
        policy = PolicyStore(policies_file()).update(key, **body.model_dump(exclude_unset=True))
        return _policy_to_response(policy)

    return router
