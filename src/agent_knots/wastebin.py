"""Tombstone records for stopped agent sessions.

Sessions are never persisted anywhere — SessionManager._sessions is pure
in-memory, and stop() simply pops one out. Without this, a session
leaves zero trace once it ends: no history, and no way to find (let
alone clean up) whatever git branch or auto-provisioned working
directory it left behind. Every stop() now writes one entry here
instead, giving the app its first real session history plus a place to
browse/delete leftovers by hand, with an optional age-based sweep.

Metadata lives in state.db (indexed session_id / task_id / stopped_at).
The session's full event history is deliberately NOT in that row — it
is written to a sibling <id>.history.json under wastebin_dir(). list()
(Task Detail's "Past sessions", the Settings Wastebin card, the Review
task list) only ever needs the small metadata fields; a real session's
history can run to tens of thousands of events, and loading that on
every list() call (every 5s poll, from several different screens) was
measured making Task Detail noticeably slow. Plain JSON for the history
file — it is not meant to be hand-edited, and json is substantially
faster than PyYAML to parse at this size. Only the one thing that
actually needs full history — reopening a stopped session's transcript
— reads it, via get_history().
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_knots.config import wastebin_dir
from agent_knots.gitutil import delete_branch_force, is_repo
from agent_knots.storage.db import get_connection


@dataclass
class WastebinEntry:
    """A snapshot of a session, taken the moment it was stopped.
    Metadata only — see get_history() for the event transcript."""
    session_id: str
    name: str = ""                # human-readable display name ("sleepy-panda")
    task_id: str | None = None
    task_title: str = ""          # denormalized — the task may be deleted later
    project_id: str | None = None
    branch: str | None = None     # only set if it survived stop() (had commits or was dirty)
    branch_base: str = ""         # needed to force-delete the branch later
    working_dir: str = ""
    is_auto_workdir: bool = False  # working_dir == config.session_workdir(id) — ours to rmtree
    role: str = ""
    advisory: bool = False
    mode: str = ""
    model: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    started_at: float = 0.0
    stopped_at: float = field(default_factory=time.time)


def _entry_from_dict(d: dict[str, Any]) -> WastebinEntry:
    return WastebinEntry(
        session_id=d["session_id"],
        name=d.get("name", ""),
        task_id=d.get("task_id"),
        task_title=d.get("task_title", ""),
        project_id=d.get("project_id"),
        branch=d.get("branch"),
        branch_base=d.get("branch_base", ""),
        working_dir=d.get("working_dir", ""),
        is_auto_workdir=d.get("is_auto_workdir", False),
        role=d.get("role", ""),
        advisory=d.get("advisory", False),
        mode=d.get("mode", ""),
        model=d.get("model", ""),
        tokens_used=d.get("tokens_used", 0),
        cost_usd=d.get("cost_usd", 0.0),
        started_at=d.get("started_at", 0.0),
        stopped_at=d.get("stopped_at", 0.0),
    )


class WastebinStore:
    """SQLite-backed metadata store; history stays in per-session JSON files."""

    _write_lock = threading.RLock()

    def __init__(self, db_path: Path, history_dir: Path | None = None) -> None:
        self._conn = get_connection(db_path)
        self._history_dir = Path(history_dir) if history_dir is not None else wastebin_dir()
        self._history_dir.mkdir(parents=True, exist_ok=True)

    def _history_path(self, session_id: str) -> Path:
        return self._history_dir / f"{session_id}.history.json"

    def add(self, entry: WastebinEntry, history: list[dict[str, Any]] | None = None) -> None:
        with self._write_lock:
            self._conn.execute(
                """
                INSERT INTO wastebin (session_id, task_id, project_id, stopped_at, data)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    project_id = excluded.project_id,
                    stopped_at = excluded.stopped_at,
                    data = excluded.data
                """,
                (
                    entry.session_id,
                    entry.task_id,
                    entry.project_id,
                    entry.stopped_at,
                    json.dumps(asdict(entry)),
                ),
            )
            self._conn.commit()
        if history:
            try:
                self._history_path(entry.session_id).write_text(json.dumps(history))
            except Exception:
                pass

    def get(self, session_id: str) -> WastebinEntry | None:
        row = self._conn.execute(
            "SELECT data FROM wastebin WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._load_json(row[0])

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        """The session's full event transcript — a separate, potentially
        large read from the metadata get()/list() above. Only call this
        for the one session actually being reopened, never in a loop
        over list()'s results."""
        path = self._history_path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def list(
        self, retention_days: int = 0, *, protected_branches: set[str] = frozenset(),
        task_id: str = "",
    ) -> list[WastebinEntry]:
        """All entries, newest-first. If retention_days is set, entries
        older than that are purged first (via delete()) rather than
        returned.

        Entries still being kept (not yet expired) and protected_branches
        both guard their branch names during that sweep — an expiring
        entry must never force-delete a branch a newer, still-kept entry
        (or a currently-active session) legitimately still points at.
        """
        if task_id:
            rows = self._conn.execute(
                "SELECT data FROM wastebin WHERE task_id = ? ORDER BY stopped_at DESC",
                (task_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT data FROM wastebin ORDER BY stopped_at DESC"
            ).fetchall()

        entries: list[WastebinEntry] = []
        for row in rows:
            entry = self._load_json(row[0])
            if entry is not None:
                entries.append(entry)

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
        """Remove an entry (and its history file) and clean up its
        leftovers.

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

        with self._write_lock:
            self._conn.execute(
                "DELETE FROM wastebin WHERE session_id = ?", (session_id,)
            )
            self._conn.commit()
        self._history_path(session_id).unlink(missing_ok=True)

    def _load_json(self, raw: str) -> WastebinEntry | None:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or "session_id" not in data:
                return None
            return _entry_from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None
