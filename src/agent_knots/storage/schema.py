"""SQLite schema for agent-knots structured state."""

from __future__ import annotations

SCHEMA_VERSION = 2

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    project     TEXT NOT NULL DEFAULT '',
    assigned_to TEXT NOT NULL DEFAULT '',
    updated_at  REAL NOT NULL,
    data        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project);
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    archived    INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    data        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects(archived);

CREATE TABLE IF NOT EXISTS wastebin (
    session_id  TEXT PRIMARY KEY,
    task_id     TEXT,
    project_id  TEXT,
    stopped_at  REAL NOT NULL,
    data        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wastebin_stopped ON wastebin(stopped_at DESC);
CREATE INDEX IF NOT EXISTS idx_wastebin_task ON wastebin(task_id);

CREATE TABLE IF NOT EXISTS usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    session_id  TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    task_id     TEXT,
    tokens      INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage(timestamp);
"""
