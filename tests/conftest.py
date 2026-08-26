"""Shared test fixtures for storage isolation."""

import pytest


@pytest.fixture(autouse=True)
def _reset_storage_between_tests(monkeypatch):
    """Close SQLite connections and drop cached stores after each test.

    Tests that set AGENT_KNOTS_HOME call reset_stores() in their own
    fixture setup too; this autouse hook catches everything else so a
    prior test's module-level connection never leaks into the next one.
    """
    yield
    from agent_knots.storage import reset_stores

    reset_stores()
