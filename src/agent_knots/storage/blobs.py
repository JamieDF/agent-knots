"""Whole-document config blobs in state.db.

One row per config document (settings, stages, roles, policies,
mcp_servers). Callers own serialization of domain objects; this module
only stores and retrieves JSON.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from agent_knots.config import db_path
from agent_knots.storage.db import get_connection

_write_lock = threading.RLock()

KEY_SETTINGS = "settings"
KEY_STAGES = "stages"
KEY_ROLES = "roles"
KEY_POLICIES = "policies"
KEY_MCP_SERVERS = "mcp_servers"


def get_blob(key: str, *, path: Path | None = None) -> Any | None:
    """Return the JSON-decoded blob for key, or None if unset."""
    conn = get_connection(path or db_path())
    row = conn.execute("SELECT data FROM config WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def set_blob(key: str, data: Any, *, path: Path | None = None) -> None:
    """Replace the blob for key with JSON-encoded data."""
    conn = get_connection(path or db_path())
    with _write_lock:
        conn.execute(
            """
            INSERT INTO config (key, data) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET data = excluded.data
            """,
            (key, json.dumps(data)),
        )
        conn.commit()


def delete_blob(key: str, *, path: Path | None = None) -> None:
    """Remove a config blob (tests / reset)."""
    conn = get_connection(path or db_path())
    with _write_lock:
        conn.execute("DELETE FROM config WHERE key = ?", (key,))
        conn.commit()
