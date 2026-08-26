"""Tests for the token/cost usage ledger."""

import time

import pytest

from agent_knots import usage
from agent_knots.storage import reset_stores


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KNOTS_HOME", str(tmp_path))
    reset_stores()
    yield
    reset_stores()


class TestProviderOf:
    def test_minimax(self):
        assert usage.provider_of("minimax-m2.7") == "minimax"

    def test_anthropic(self):
        assert usage.provider_of("claude-sonnet-4-20250514") == "anthropic"

    def test_openai(self):
        assert usage.provider_of("gpt-4o-mini") == "openai"

    def test_ollama(self):
        assert usage.provider_of("llama3") == "ollama"

    def test_other(self):
        assert usage.provider_of("some-custom-model") == "other"


class TestRecordAndSummary:
    def test_summary_empty_ledger(self):
        s = usage.summary()
        assert s["today"] == {"tokens": 0, "cost_usd": 0}
        assert s["month"] == {"tokens": 0, "cost_usd": 0}
        assert s["by_provider"] == []
        assert s["top_tasks"] == []

    def test_record_appears_in_today_and_month(self):
        now = time.time()
        usage.record(usage.UsageEntry(
            session_id="s1", model="minimax-m2.7", task_id="T-1",
            tokens=100, cost_usd=0.01,
        ))
        s = usage.summary(now=now)
        assert s["today"]["tokens"] == 100
        assert s["month"]["tokens"] == 100

    def test_old_entry_excluded_from_today(self):
        now = time.time()
        old = now - 40 * 86400  # older than the 30-day month window too
        usage.record(usage.UsageEntry(
            session_id="s1", model="gpt-4o-mini", tokens=50, cost_usd=0.005,
            timestamp=old,
        ))
        s = usage.summary(now=now)
        assert s["today"]["tokens"] == 0
        assert s["month"]["tokens"] == 0

    def test_by_provider_groups_correctly(self):
        now = time.time()
        usage.record(usage.UsageEntry(
            model="minimax-m2.7", tokens=100, cost_usd=0.01, timestamp=now,
        ))
        usage.record(usage.UsageEntry(
            model="minimax-m2.7", tokens=50, cost_usd=0.005, timestamp=now,
        ))
        usage.record(usage.UsageEntry(
            model="gpt-4o-mini", tokens=10, cost_usd=0.001, timestamp=now,
        ))
        s = usage.summary(now=now)
        by_provider = {r["provider"]: r for r in s["by_provider"]}
        assert by_provider["minimax"]["tokens"] == 150
        assert by_provider["openai"]["tokens"] == 10

    def test_top_tasks_sorted_by_tokens(self):
        now = time.time()
        usage.record(usage.UsageEntry(task_id="T-1", tokens=10, timestamp=now))
        usage.record(usage.UsageEntry(task_id="T-2", tokens=100, timestamp=now))
        usage.record(usage.UsageEntry(task_id=None, tokens=999, timestamp=now))
        s = usage.summary(now=now)
        assert s["top_tasks"][0]["task_id"] == "T-2"
        assert all(t["task_id"] for t in s["top_tasks"])  # null task_id excluded

    def test_cost_since(self):
        now = time.time()
        usage.record(usage.UsageEntry(cost_usd=1.0, timestamp=now - 100))
        usage.record(usage.UsageEntry(cost_usd=2.0, timestamp=now - 10))
        assert usage.cost_since(now - 50) == 2.0
        assert usage.cost_since(now - 200) == 3.0
