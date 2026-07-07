"""Model provider configuration.

API keys and model settings are resolved in this order of precedence:
  1. CLI flags (--api-key, --model, --base-url) — one-off overrides
  2. Environment variables (AGENTJAM_API_KEY, AGENTJAM_MODEL, AGENTJAM_BASE_URL)
  3. Settings file (~/.agentjam/settings.yaml) — persistent configuration

The settings file format under the [agent] section:
    default_model: openai/gpt-4o-mini
    api_key: sk-...
    base_url: https://api.minimax.io/v1   # optional, for non-OpenAI providers

For MiniMax specifically, use:
    export AGENTJAM_MODEL=openai/minimax-m2.7
    export AGENTJAM_BASE_URL=https://api.minimax.io/v1
    export AGENTJAM_API_KEY=<your-minimax-key>
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from agentjam.config import settings_file


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
    if env_model := os.environ.get("AGENTJAM_MODEL"):
        resolved_model = env_model
    if env_key := os.environ.get("AGENTJAM_API_KEY"):
        resolved_key = env_key
    if env_url := os.environ.get("AGENTJAM_BASE_URL"):
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
    path = settings_file()
    if not path.exists():
        return {}

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    agent_section = data.get("agent", {})
    if not isinstance(agent_section, dict):
        return {}

    return agent_section
