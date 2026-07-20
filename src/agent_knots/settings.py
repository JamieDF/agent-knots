"""Global settings store — reads/writes ~/.agent-knots/settings.yaml.

Settings are layered: the file on disk is the source of truth.
Env vars can override at runtime (see provider.py), but the GUI
setup wizard writes directly to this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

from agent_knots.config import settings_file


@dataclass
class AgentSettings:
    default_model: str = "openai/gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    default_mode: str = "agent"
    runtime: str = "inprocess"  # "inprocess" or "subprocess"


@dataclass
class Settings:
    agent: AgentSettings = field(default_factory=AgentSettings)


def load() -> Settings:
    """Load settings from disk. Returns defaults if file doesn't exist."""
    path = settings_file()
    if not path.exists():
        return Settings()

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return Settings()

    if not isinstance(data, dict):
        return Settings()

    agent_data = data.get("agent", {})
    agent = AgentSettings(
        default_model=agent_data.get("default_model", AgentSettings.default_model),
        api_key=agent_data.get("api_key", ""),
        base_url=agent_data.get("base_url", ""),
        default_mode=agent_data.get("default_mode", "agent"),
        runtime=agent_data.get("runtime", "inprocess"),
    )

    return Settings(agent=agent)


def save(settings: Settings) -> None:
    """Persist settings to disk atomically."""
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "agent": asdict(settings.agent),
    }

    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(data, default_flow_style=False))
    tmp.chmod(0o600)
    tmp.rename(path)


def is_configured() -> bool:
    """Return True if the user has set up at least an API key."""
    s = load()
    return bool(s.agent.api_key)


def mask_key(key: str) -> str:
    """Return a masked version of an API key for display."""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "..." + key[-4:]
