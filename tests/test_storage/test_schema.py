"""Tests for SQLite schema initialization."""

import pytest

from agent_knots.config import db_path
from agent_knots.storage import reset_stores, task_store
from agent_knots.storage.db import get_connection, schema_version
from agent_knots.storage.schema import SCHEMA_VERSION


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    reset_stores()
    yield
    reset_stores()


def test_schema_version_set_on_first_store_access():
    task_store()
    conn = get_connection(db_path())
    assert schema_version(conn) == SCHEMA_VERSION


def test_wal_mode_enabled():
    conn = get_connection(db_path())
    row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row is not None
    assert row[0].lower() == "wal"


def test_tasks_table_exists():
    conn = get_connection(db_path())
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
    ).fetchone()
    assert row is not None


def test_projects_table_exists():
    conn = get_connection(db_path())
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
    ).fetchone()
    assert row is not None


def test_wastebin_and_usage_tables_exist():
    conn = get_connection(db_path())
    for name in ("wastebin", "usage"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        assert row is not None


def test_schema_upgrades_from_v1():
    """Existing Phase 1 DBs pick up wastebin/usage tables and bump version."""
    from agent_knots.storage.db import set_schema_version

    conn = get_connection(db_path())
    set_schema_version(conn, 1)
    reset_stores()

    conn = get_connection(db_path())
    assert schema_version(conn) == SCHEMA_VERSION
    for name in ("wastebin", "usage"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        assert row is not None
