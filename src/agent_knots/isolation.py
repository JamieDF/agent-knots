"""Session isolation — workspace confinement.

Each session gets its own workspace directory. Shell and editor tools
are swapped with sandboxed versions that resolve paths relative to the
workspace root and reject traversal attempts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkspaceSandbox:
    """Holds workspace config for a session.

    The sandboxed shell and editor tools use this to resolve paths
    and confine execution to the workspace directory.
    """
    workspace_dir: str
    allowed_urls: list[str]
    max_output: int = 1 << 20
    max_file_size: int = 10 << 20

    @property
    def exists(self) -> bool:
        return bool(self.workspace_dir) and Path(self.workspace_dir).exists()


def create_sandbox(workspace_dir: str = "") -> WorkspaceSandbox | None:
    """Create a workspace sandbox config.

    Returns None if no workspace directory is configured or it doesn't exist.
    """
    if not workspace_dir or not Path(workspace_dir).exists():
        return None

    from agent_knots import settings
    s = settings.load()
    allowed: list[str] = []
    if s.agent.base_url:
        base = s.agent.base_url.rstrip("/")
        allowed.append(f"{base}/*")

    return WorkspaceSandbox(
        workspace_dir=workspace_dir,
        allowed_urls=allowed,
    )
