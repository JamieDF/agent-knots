"""Git helpers shared by the review/filesystem-browse routers and the
session manager's per-session branch handling.

Lives at the package root rather than under cockpit/web/ because
session/manager.py needs it too, and importing from the web layer into
the session layer would invert the dependency direction.
"""

import re
import subprocess
from pathlib import Path


def _run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Run a git command scoped to a workspace repo the user configured
    themselves (Project.repository) — never an arbitrary path, never
    shell=True (no injection risk from list-form subprocess args)."""
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=10,
    )


def _git_diff_stat(repo: Path) -> list[dict]:
    """Per-file added/deleted line counts for uncommitted changes."""
    result = _run_git(repo, ["diff", "--numstat"])
    items = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, deleted, path = parts
            items.append({
                "path": path,
                "added": int(added) if added.isdigit() else 0,
                "deleted": int(deleted) if deleted.isdigit() else 0,
            })
    return items


def _git_diff_for_file(repo: Path, path: str) -> str:
    return _run_git(repo, ["diff", "--", path]).stdout


def _github_url_from_remote(remote_url: str) -> str | None:
    """Best-effort parse of a git remote URL into a browsable
    https://github.com/owner/repo link, covering the SSH, ssh://, and
    HTTPS forms `git remote get-url origin` can return."""
    url = remote_url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    for pattern in (r"^git@github\.com:(.+)$", r"^ssh://git@github\.com/(.+)$", r"^https?://github\.com/(.+)$"):
        m = re.match(pattern, url)
        if m:
            return f"https://github.com/{m.group(1)}"
    return None
