"""Token/cost usage ledger — append-only JSONL, same pattern as the vault
audit log. One entry is recorded whenever a session ends (see
session/manager.py) with tokens actually used.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class UsageEntry:
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    model: str = ""
    task_id: str | None = None
    tokens: int = 0
    cost_usd: float = 0.0


def provider_of(model: str) -> str:
    """Best-effort provider name from a model id, for the Settings 'by
    provider' usage breakdown. Cosmetic grouping only — never used for
    routing or billing decisions."""
    m = model.lower()
    if "minimax" in m:
        return "minimax"
    if "claude" in m:
        return "anthropic"
    if "llama" in m or "ollama" in m:
        return "ollama"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    return "other"


def record(path: Path, entry: UsageEntry) -> None:
    """Append one usage entry to the ledger."""
    data = json.dumps({
        "timestamp": entry.timestamp,
        "session_id": entry.session_id,
        "model": entry.model,
        "task_id": entry.task_id,
        "tokens": entry.tokens,
        "cost_usd": entry.cost_usd,
    })
    with open(path, "a") as fh:
        fh.write(data + "\n")


def _read_all(path: Path) -> list[UsageEntry]:
    if not path.exists():
        return []
    entries: list[UsageEntry] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries.append(UsageEntry(
            timestamp=d.get("timestamp", 0.0),
            session_id=d.get("session_id", ""),
            model=d.get("model", ""),
            task_id=d.get("task_id"),
            tokens=d.get("tokens", 0),
            cost_usd=d.get("cost_usd", 0.0),
        ))
    return entries


def today_start(now: float | None = None) -> float:
    now = now if now is not None else time.time()
    return now - (now % 86400)


def cost_since(path: Path, since: float) -> float:
    """Sum of cost_usd for entries at or after `since`. Used by the
    spend-cap policy check — kept separate from summary() so enforcement
    doesn't have to compute the full breakdown on every session start."""
    return sum(e.cost_usd for e in _read_all(path) if e.timestamp >= since)


def summary(path: Path, now: float | None = None) -> dict:
    """Aggregate the ledger into today/month totals, a per-provider
    breakdown, and the top tasks by token count."""
    now = now if now is not None else time.time()
    today_start = now - (now % 86400)
    month_start = now - 30 * 86400

    entries = _read_all(path)

    today = [e for e in entries if e.timestamp >= today_start]
    month = [e for e in entries if e.timestamp >= month_start]

    by_provider: dict[str, dict] = {}
    for e in month:
        p = provider_of(e.model)
        row = by_provider.setdefault(p, {"provider": p, "tokens": 0, "cost_usd": 0.0})
        row["tokens"] += e.tokens
        row["cost_usd"] += e.cost_usd

    by_task: dict[str, dict] = {}
    for e in month:
        if not e.task_id:
            continue
        row = by_task.setdefault(e.task_id, {"task_id": e.task_id, "tokens": 0})
        row["tokens"] += e.tokens

    top_tasks = sorted(by_task.values(), key=lambda r: r["tokens"], reverse=True)[:5]

    return {
        "today": {"tokens": sum(e.tokens for e in today), "cost_usd": sum(e.cost_usd for e in today)},
        "month": {"tokens": sum(e.tokens for e in month), "cost_usd": sum(e.cost_usd for e in month)},
        "by_provider": sorted(by_provider.values(), key=lambda r: r["tokens"], reverse=True),
        "top_tasks": top_tasks,
    }
