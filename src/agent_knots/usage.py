"""Token/cost usage ledger — append-only rows in state.db.

One entry is recorded whenever a session ends (see session/manager.py)
with tokens actually used.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from agent_knots.config import db_path
from agent_knots.storage.db import get_connection


@dataclass
class UsageEntry:
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    model: str = ""
    task_id: str | None = None
    tokens: int = 0
    cost_usd: float = 0.0


_write_lock = threading.RLock()


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


def record(entry: UsageEntry) -> None:
    """Append one usage entry to the ledger."""
    conn = get_connection(db_path())
    with _write_lock:
        conn.execute(
            """
            INSERT INTO usage (timestamp, session_id, model, task_id, tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.timestamp,
                entry.session_id,
                entry.model,
                entry.task_id,
                entry.tokens,
                entry.cost_usd,
            ),
        )
        conn.commit()


def _read_since(since: float = 0.0) -> list[UsageEntry]:
    conn = get_connection(db_path())
    rows = conn.execute(
        """
        SELECT timestamp, session_id, model, task_id, tokens, cost_usd
        FROM usage
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (since,),
    ).fetchall()
    return [
        UsageEntry(
            timestamp=row[0],
            session_id=row[1] or "",
            model=row[2] or "",
            task_id=row[3],
            tokens=row[4] or 0,
            cost_usd=row[5] or 0.0,
        )
        for row in rows
    ]


def today_start(now: float | None = None) -> float:
    now = now if now is not None else time.time()
    return now - (now % 86400)


def cost_since(since: float) -> float:
    """Sum of cost_usd for entries at or after `since`. Used by the
    spend-cap policy check — kept separate from summary() so enforcement
    doesn't have to compute the full breakdown on every session start."""
    conn = get_connection(db_path())
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE timestamp >= ?",
        (since,),
    ).fetchone()
    return float(row[0]) if row is not None else 0.0


def summary(now: float | None = None) -> dict:
    """Aggregate the ledger into today/month totals, a per-provider
    breakdown, and the top tasks by token count."""
    now = now if now is not None else time.time()
    day_start = now - (now % 86400)
    month_start = now - 30 * 86400

    entries = _read_since(month_start)

    today = [e for e in entries if e.timestamp >= day_start]
    month = entries

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
        "today": {
            "tokens": sum(e.tokens for e in today),
            "cost_usd": sum(e.cost_usd for e in today),
        },
        "month": {
            "tokens": sum(e.tokens for e in month),
            "cost_usd": sum(e.cost_usd for e in month),
        },
        "by_provider": sorted(by_provider.values(), key=lambda r: r["tokens"], reverse=True),
        "top_tasks": top_tasks,
    }
