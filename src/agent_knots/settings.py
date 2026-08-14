"""Global settings store — reads/writes ~/.agent-knots/settings.yaml.

Settings are layered: the file on disk is the source of truth.
Env vars can override at runtime (see provider.py), but the GUI
setup wizard writes directly to this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from agent_knots.config import settings_file
from agent_knots.yamlfile import atomic_write_yaml, safe_read_yaml


@dataclass
class AgentSettings:
    default_model: str = "openai/gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    default_mode: str = "agent"
    runtime: str = "inprocess"


@dataclass
class ProviderProfile:
    """A named, saved model-provider config. `agent` above always holds
    whichever profile is currently active — "Set default" on the
    Settings screen copies a profile's fields into `agent` rather than
    resolve_provider() having to know about the list at all, so the
    existing precedence logic in resolve_provider() stays untouched."""
    name: str
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@dataclass
class IntegrationsSettings:
    """Config-only — no OAuth flow or push infra exists yet. Persisted
    so the Settings screen has something real to toggle and read back.

    `github_pr_on_review` used to live here as a stub with nothing
    behind it. It's gone: its name baked in a timing (fire on entering
    review) that publishes unapproved work, and the behaviour it hinted
    at is now `finish_action` / `finish_when` below.
    """
    phone_push: bool = False


# How a task's branch gets finished once its work is approved, and when.
# Two axes rather than one setting, because they're genuinely
# independent: *what* lands the work, and *whether* you press a button.
FINISH_ACTIONS = ("merge", "pull_request", "none")
FINISH_WHEN = ("manual", "on_approve")


@dataclass
class WastebinSettings:
    """0 = keep stopped-session tombstones (and their leftover
    branches/workdirs) forever; otherwise WastebinStore.list() purges
    anything older than this on every read."""
    retention_days: int = 30


@dataclass
class Settings:
    agent: AgentSettings = field(default_factory=AgentSettings)
    providers: list[ProviderProfile] = field(default_factory=list)
    default_provider: str = ""
    integrations: IntegrationsSettings = field(default_factory=IntegrationsSettings)
    wastebin: WastebinSettings = field(default_factory=WastebinSettings)
    # "" = let config.workspaces_root() pick the default. Read only by
    # that function, which is also why this is a bare path string rather
    # than a nested section — there's nothing else to group it with.
    workspaces_root: str = ""
    # "" = config.DEFAULT_PLAYGROUND_REPO. Override to point the
    # playground at a fork, or at a local path while developing.
    playground_repo: str = ""
    # Global default for how tasks get finished; a workspace can
    # override either. "merge" suits a solo local repo, "pull_request" a
    # team repo with a protected mainline — merging locally into a
    # protected branch just fails on push.
    finish_action: str = "merge"
    finish_when: str = "manual"


def load() -> Settings:
    """Load settings from disk. Returns defaults if file doesn't exist."""
    path = settings_file()
    if not path.exists():
        return Settings()

    data = safe_read_yaml(path) or {}
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

    providers = [
        ProviderProfile(
            name=p.get("name", ""), model=p.get("model", ""),
            api_key=p.get("api_key", ""), base_url=p.get("base_url", ""),
        )
        for p in data.get("providers", [])
        if isinstance(p, dict)
    ]

    integrations_data = data.get("integrations", {})
    integrations = IntegrationsSettings(
        phone_push=integrations_data.get("phone_push", False),
    )

    wastebin_data = data.get("wastebin", {})
    wastebin = WastebinSettings(
        retention_days=wastebin_data.get("retention_days", WastebinSettings.retention_days),
    )

    return Settings(
        agent=agent,
        providers=providers,
        default_provider=data.get("default_provider", ""),
        integrations=integrations,
        wastebin=wastebin,
        workspaces_root=data.get("workspaces_root", ""),
        playground_repo=data.get("playground_repo", ""),
        finish_action=data.get("finish_action", "merge"),
        finish_when=data.get("finish_when", "manual"),
    )


def save(settings: Settings) -> None:
    """Persist settings to disk atomically."""
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "agent": asdict(settings.agent),
        "providers": [asdict(p) for p in settings.providers],
        "default_provider": settings.default_provider,
        "integrations": asdict(settings.integrations),
        "wastebin": asdict(settings.wastebin),
        "workspaces_root": settings.workspaces_root,
        "playground_repo": settings.playground_repo,
        "finish_action": settings.finish_action,
        "finish_when": settings.finish_when,
    }
    # sort_keys=True (not the atomic_write_yaml default) to preserve this
    # file's pre-existing on-disk key order.
    atomic_write_yaml(path, data, sort_keys=True)


def mask_key(key: str) -> str:
    """Return a masked version of an API key for display."""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "..." + key[-4:]
