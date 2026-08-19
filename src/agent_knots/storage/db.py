"""SQLite connection lifecycle for agent-knots state.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agent_knots.storage.schema import DDL, SCHEMA_VERSION

_connection: sqlite3.Connection | None = None
_connection_path: Path | None = None


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Return a module-level connection for db_path, creating schema if needed."""
    global _connection, _connection_path
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if _connection is not None and _connection_path == db_path:
        return _connection

    if _connection is not None:
        _connection.close()
        _connection = None
        _connection_path = None

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(DDL)
    version = schema_version(conn)
    if version is None or version < SCHEMA_VERSION:
        set_schema_version(conn, SCHEMA_VERSION)
    conn.commit()
    _connection = conn
    _connection_path = db_path
    return conn


def schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the stored schema version, or None if unset."""
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        return None
    return int(row[0])


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()


def close_connection() -> None:
    """Close the module-level connection (tests only)."""
    global _connection, _connection_path
    if _connection is not None:
        _connection.close()
        _connection = None
        _connection_path = None


def current_schema_version() -> int:
    return SCHEMA_VERSION
