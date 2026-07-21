"""Policy rule model + defaults."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Policy:
    key: str
    label: str
    description: str = ""
    enabled: bool = False
    value: str = ""  # e.g. the dollar amount for spend_cap; unused by pure toggles
    enforced: bool = False  # whether this key actually has a real enforcement hook


DEFAULT_POLICIES: list[Policy] = [
    Policy(
        key="migrations_guard",
        label="Guard database migrations",
        description="Warn before an agent runs a schema migration.",
        enabled=False,
        enforced=False,
    ),
    Policy(
        key="pause_after_test_failures",
        label="Pause after 2 test failures",
        description="Stop and ask for guidance after repeated test failures in one session.",
        enabled=False,
        enforced=False,
    ),
    Policy(
        key="spend_cap",
        label="Daily spend cap",
        description="Block new sessions once today's estimated spend reaches this amount (USD).",
        enabled=False,
        value="10.00",
        enforced=True,
    ),
    Policy(
        key="no_sudo",
        label="No sudo",
        description="Refuse to run commands that invoke sudo.",
        enabled=False,
        enforced=False,
    ),
]
