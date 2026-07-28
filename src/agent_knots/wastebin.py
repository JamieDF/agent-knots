"""Tombstone records for stopped agent sessions.

Sessions are never persisted anywhere — SessionManager._sessions is pure
in-memory, and stop() simply pops one out. Without this, a session
leaves zero trace once it ends: no history, and no way to find (let
alone clean up) whatever git branch or auto-provisioned working
directory it left behind. Every stop() now writes one entry here
instead, giving the app its first real session history plus a place to
browse/delete leftovers by hand, with an optional age-based sweep.

One YAML file per session under wastebin_dir(), same layout as
task/store.py's TaskStore — no locking needed, since each stop() only
ever writes its own session's file, never contended by another.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_knots.gitutil import delete_branch_force, is_repo
from agent_knots.yamlfile import atomic_write_yaml, safe_read_yaml


@dataclass
class WastebinEntry:
    """A snapshot of a session, taken the moment it was stopped."""
    session_id: str
    task_id: str | None = None
    task_title: str = ""          # denormalized — the task may be deleted later
    project_id: str | None = None
    branch: str | None = None     # only set if it survived stop() (had commits or was dirty)
    branch_base: str = ""         # needed to force-delete the branch later
    working_dir: str = ""
    is_auto_workdir: bool = False  # working_dir == config.session_workdir(id) — ours to rmtree
    role: str = ""
    advisory: bool = False
    model: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    started_at: float = 0.0
    stopped_at: float = field(default_factory=time.time)


def _entry_from_dict(d: dict[str, Any]) -> WastebinEntry:
    return WastebinEntry(
        session_id=d["session_id"],
        task_id=d.get("task_id"),
        task_title=d.get("task_title", ""),
        project_id=d.get("project_id"),
        branch=d.get("branch"),
        branch_base=d.get("branch_base", ""),
        working_dir=d.get("working_dir", ""),
        is_auto_workdir=d.get("is_auto_workdir", False),
        role=d.get("role", ""),
        advisory=d.get("advisory", False),
        model=d.get("model", ""),
        tokens_used=d.get("tokens_used", 0),
        cost_usd=d.get("cost_usd", 0.0),
        started_at=d.get("started_at", 0.0),
        stopped_at=d.get("stopped_at", 0.0),
    )


class WastebinStore:
    def __init__(self, wastebin_dir: Path) -> None:
        self._dir = Path(wastebin_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.yaml"

    def add(self, entry: WastebinEntry) -> None:
        atomic_write_yaml(self._path(entry.session_id), asdict(entry))

    def get(self, session_id: str) -> WastebinEntry | None:
        data = safe_read_yaml(self._path(session_id))
        if not isinstance(data, dict) or "session_id" not in data:
            return None
        try:
            return _entry_from_dict(data)
        except KeyError:
            return None

    def list(
        self, retention_days: int = 0, *, protected_branches: set[str] = frozenset(),
    ) -> list[WastebinEntry]:
        """All entries, newest-first. If retention_days is set, entries
        older than that are purged first (via delete()) rather than
        returned.

        Entries still being kept (not yet expired) and protected_branches
        both guard their branch names during that sweep — an expiring
        entry must never force-delete a branch a newer, still-kept entry
        (or a currently-active session) legitimately still points at.
        """
        entries = []
        for path in sorted(self._dir.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
            data = safe_read_yaml(path)
            if not isinstance(data, dict) or "session_id" not in data:
                continue
            try:
                entries.append(_entry_from_dict(data))
            except KeyError:
                continue

        if not retention_days:
            return entries

        cutoff = time.time() - retention_days * 86400
        keep = [e for e in entries if e.stopped_at >= cutoff]
        expired = [e for e in entries if e.stopped_at < cutoff]
        kept_branches = {e.branch for e in keep if e.branch} | set(protected_branches)
        for e in expired:
            try:
                self.delete(e.session_id, protected_branches=kept_branches)
            except Exception:
                pass
        return keep

    def delete(self, session_id: str, *, protected_branches: set[str] = frozenset()) -> None:
        """Remove an entry and clean up its leftovers.

        Force-deletes the branch (regardless of commits) only if it's
        set and not in protected_branches. rmtrees working_dir only if
        it's one of our own auto-provisioned workdirs — never a real
        project repository, that's the user's code, not ours to delete.
        Every cleanup step is best-effort: a missing repo or an
        already-gone directory must not stop the record itself from
        being removed.

        Raises ValueError if the entry doesn't exist.
        """
        entry = self.get(session_id)
        if entry is None:
            raise ValueError(f"wastebin entry {session_id!r} not found")

        if entry.branch and entry.branch not in protected_branches and entry.working_dir:
            try:
                repo = Path(entry.working_dir)
                if is_repo(repo):
                    delete_branch_force(repo, entry.branch, entry.branch_base or "main")
            except Exception:
                pass

        if entry.is_auto_workdir and entry.working_dir:
            try:
                shutil.rmtree(entry.working_dir, ignore_errors=True)
            except Exception:
                pass

        self._path(session_id).unlink(missing_ok=True)
