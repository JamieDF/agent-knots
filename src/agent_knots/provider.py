"""Model provider configuration.

API keys and model settings are resolved in this order of precedence:
  1. CLI flags (--api-key, --model, --base-url) — one-off overrides
  2. Environment variables (AGENT_KNOTS_API_KEY, AGENT_KNOTS_MODEL, AGENT_KNOTS_BASE_URL)
  3. Settings file (~/.agent-knots/settings.yaml) — persistent configuration

The settings file format under the [agent] section:
    default_model: openai/gpt-4o-mini
    api_key: sk-...
    base_url: https://api.minimax.io/v1   # optional, for non-OpenAI providers

For MiniMax specifically, use:
    export AGENT_KNOTS_MODEL=minimax-m2.7
    export AGENT_KNOTS_BASE_URL=https://api.minimax.io/v1
    export AGENT_KNOTS_API_KEY=<your-minimax-key>

Note: model IDs are passed as-is to strands.models.openai.OpenAIModel,
which does not strip a "provider/" prefix (that convention only means
something under a routing layer like litellm, which isn't used here
despite being a listed dependency) — use the bare model ID the target
API actually expects (e.g. "gpt-4o-mini", "minimax-m2.7"), not
"openai/gpt-4o-mini". Confirmed against a real MiniMax M2.7 call, which
400s on "unknown model" with the prefixed form.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ProviderConfig:
    """Resolved model provider configuration."""
    model: str = "openai/gpt-4o-mini"
    api_key: str = ""
    base_url: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


def resolve_provider(
    model: str = "",
    api_key: str = "",
    base_url: str | None = None,
) -> ProviderConfig:
    """Resolve provider config from CLI flags, env vars, and settings file.

    Args:
        model: CLI --model flag (highest priority if non-empty).
        api_key: CLI --api-key flag.
        base_url: CLI --base-url flag.

    Returns:
        ProviderConfig with the resolved values.
    """
    # Start with settings file (lowest priority).
    settings = _load_settings()

    resolved_model = settings.get("default_model", "openai/gpt-4o-mini")
    resolved_key = settings.get("api_key", "")
    resolved_url = settings.get("base_url", None)

    # Env vars override settings file.
    if env_model := os.environ.get("AGENT_KNOTS_MODEL"):
        resolved_model = env_model
    if env_key := os.environ.get("AGENT_KNOTS_API_KEY"):
        resolved_key = env_key
    if env_url := os.environ.get("AGENT_KNOTS_BASE_URL"):
        resolved_url = env_url

    # CLI flags override everything.
    if model:
        resolved_model = model
    if api_key:
        resolved_key = api_key
    if base_url is not None:
        resolved_url = base_url or None

    return ProviderConfig(
        model=resolved_model,
        api_key=resolved_key,
        base_url=resolved_url,
    )


def _load_settings() -> dict[str, str]:
    """Load the [agent] section from settings.yaml, if it exists."""
    from agent_knots.settings import load as load_settings

    s = load_settings()
    return {
        "default_model": s.agent.default_model,
        "api_key": s.agent.api_key,
        "base_url": s.agent.base_url,
    }
