#!/usr/bin/env python3
"""Live e2e: playground clone → agent sessions → done + review tasks.

Requires a running cockpit (``agent-knots launch --web --port 8090``) with a
real LLM provider configured (env vars or Settings). Unlike the Playwright
suite, this exercises the full stack against the managed Palette playground
clone: SQLite task state, git branch isolation, agent tools, both auto-finish
and human-review workflows, and wastebin.

Phase A — smoke task (``review_gate: none``):
  agent finishes to ``done`` with repo work.

Phase B — seeded "Dark mode" task (default ``review_gate: manual``):
  agent implements a minimal slice, marks criteria, moves to ``review`` for a
  human — not ``done``.

Usage::

    # terminal 1 — provider via env (example: DeepSeek V4 Flash)
    export AGENT_KNOTS_API_KEY=...
    export AGENT_KNOTS_MODEL=deepseek-v4-flash
    export AGENT_KNOTS_BASE_URL=https://api.deepseek.com/v1
    uv run agent-knots launch --web --port 8090

    # terminal 2 — isolated home recommended for repeat runs
    AGENT_KNOTS_HOME=/tmp/ak-e2e uv run python scripts/e2e_playground_agent.py

Exit 0 on pass, 1 on failure.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx

DEFAULT_BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8090")
DEFAULT_TIMEOUT = int(os.environ.get("E2E_PLAYGROUND_TIMEOUT", "480"))
SMOKE_PHASE_TIMEOUT = int(os.environ.get("E2E_SMOKE_TIMEOUT", "120"))
REVIEW_PHASE_TIMEOUT = int(os.environ.get("E2E_REVIEW_TIMEOUT", "360"))
PLAYGROUND_PROJECT = "playground"

E2E_TASK_TITLE = "E2E smoke: file header comment"
E2E_CRITERION = (
    "A single-line comment at the top of src/color.ts describes the file"
)
DARK_MODE_TITLE = "Dark mode"

SMOKE_PROMPT = f"""\
Automated e2e smoke test. Use exactly these task tools, in order, then stop:

1. Edit src/color.ts — add ONE comment line at the very top of the file.
2. mark_criterion_met(task_id=<attached task>, criterion="{E2E_CRITERION}")
3. log_progress(task_id=<attached task>, entry="Added header comment to src/color.ts", status="done")

Rules: do not use shell, update_task_status, or any other tools. After step 3, stop.
"""

DARK_MODE_PROMPT = """\
Automated e2e test on the attached Dark mode task. Implement a minimal slice only:

1. Respect prefers-color-scheme by default (use existing theme/CSS patterns in the repo).
2. Add a manual theme toggle that overrides OS setting and persists (localStorage is fine).
3. mark_criterion_met for EACH acceptance criterion on the task (exact text from read_task).
4. log_progress(task_id=<attached task>, entry="Dark mode ready for human review", status="review")

Rules: do NOT move the task to done — review_gate requires a human. Stop after step 4.
Do not run dev servers or full test suites.
"""


def _home() -> Path:
    if env := os.environ.get("AGENT_KNOTS_HOME"):
        return Path(env).expanduser()
    return Path.home() / ".agent-knots"


def _token() -> str:
    path = _home() / "cockpit.token"
    if not path.is_file():
        raise SystemExit(f"missing auth token: {path} (is the cockpit running?)")
    return path.read_text().strip()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def repo_work_vs_main(repo: Path, branch: str, base: str = "main") -> tuple[bool, str]:
    """True when the session branch has commits or a diff vs main."""
    if _git(repo, "rev-parse", "--verify", branch).returncode != 0:
        return False, f"branch {branch!r} not found"

    ahead = _git(repo, "rev-list", "--count", f"{base}..{branch}")
    if ahead.returncode == 0:
        n = int((ahead.stdout or "0").strip() or "0")
        if n > 0:
            return True, f"{n} commit(s) on {branch} ahead of {base}"

    diff = _git(repo, "diff", f"{base}...{branch}", "--stat")
    if diff.returncode == 0 and diff.stdout.strip():
        return True, f"committed diff {base}...{branch}: {diff.stdout.strip()[:240]}"

    head = _git(repo, "symbolic-ref", "--short", "HEAD")
    if head.returncode == 0 and head.stdout.strip() == branch:
        wt = _git(repo, "diff", base, "--stat")
        if wt.returncode == 0 and wt.stdout.strip():
            return True, f"working tree diff vs {base}: {wt.stdout.strip()[:240]}"

    return False, "no commits or diff yet"


def all_criteria_met(task: dict) -> bool:
    criteria = task.get("acceptance_criteria") or []
    met = set(task.get("criteria_met") or [])
    return bool(criteria) and all(c in met for c in criteria)


def find_playground_task(client: httpx.Client, title: str) -> dict:
    r = client.get("/api/tasks", params={"project": PLAYGROUND_PROJECT})
    r.raise_for_status()
    for task in r.json().get("tasks", []):
        if task.get("title") == title:
            full = client.get(f"/api/tasks/{task['id']}")
            full.raise_for_status()
            return full.json()
    raise SystemExit(f"playground task not found: {title!r}")


def wait_for_task_status(
    client: httpx.Client,
    *,
    repo: Path,
    branch: str,
    task_id: str,
    session_id: str,
    target_status: str,
    timeout: float,
    poll: float = 5.0,
    nudge_after: float = 30.0,
) -> tuple[bool, str, dict]:
    deadline = time.time() + timeout
    last_note = "waiting"
    task: dict = {}
    ready_at: float | None = None
    nudged = False
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        work_ok, work_note = repo_work_vs_main(repo, branch)
        status = task.get("status", "?")

        if status == target_status:
            if work_ok:
                return True, f"task {target_status}; {work_note}", task
            last_note = f"task {target_status} but {work_note}"
        elif work_ok and all_criteria_met(task):
            if ready_at is None:
                ready_at = time.time()
            elif not nudged and time.time() - ready_at >= nudge_after:
                client.post(
                    f"/api/agent/{session_id}/send",
                    data={
                        "message": (
                            f'Work is done and all criteria are met. Call '
                            f'log_progress(task_id="{task_id}", '
                            f'entry="Ready for {"review" if target_status == "review" else "done"}", '
                            f'status="{target_status}") now, then stop.'
                        ),
                    },
                )
                nudged = True
                last_note = f"nudged agent to move to {target_status}"
            else:
                last_note = f"status={status}; waiting for {target_status} ({work_note})"
        elif work_ok:
            if ready_at is None:
                ready_at = time.time()
            elif not nudged and time.time() - ready_at >= nudge_after:
                criteria = task.get("acceptance_criteria") or []
                crit_hint = "; ".join(criteria[:2])
                client.post(
                    f"/api/agent/{session_id}/send",
                    data={
                        "message": (
                            f'Code changes are in place. mark_criterion_met for each '
                            f'criterion ({crit_hint}), then log_progress(task_id="{task_id}", '
                            f'entry="Ready for review", status="{target_status}") and stop.'
                        ),
                    },
                )
                nudged = True
                last_note = f"nudged agent to mark criteria and move to {target_status}"
            else:
                last_note = f"status={status}; repo work: {work_note}"
        else:
            ready_at = None
            last_note = f"status={status}; {work_note}"

        time.sleep(poll)

    return False, f"timed out after {timeout:.0f}s ({last_note})", task


def stop_playground_sessions(client: httpx.Client) -> int:
    """Stop any live playground sessions so git branching isn't blocked."""
    r = client.get("/api/agents", params={"project": PLAYGROUND_PROJECT})
    r.raise_for_status()
    stopped = 0
    for agent in r.json().get("agents", []):
        client.delete(f"/api/agent/{agent['id']}")
        stopped += 1
    if stopped:
        time.sleep(1)
    return stopped


def start_session(
    client: httpx.Client, *, task_id: str, prompt: str,
) -> tuple[str, str]:
    r = client.post(
        "/api/sessions",
        json={
            "prompt": prompt,
            "mode": "agent",
            "task_id": task_id,
            "project_id": PLAYGROUND_PROJECT,
        },
    )
    if r.status_code != 200:
        raise SystemExit(f"start session failed: {r.status_code} {r.text}")
    session_id = r.json()["id"]

    deadline = time.time() + 30.0
    branch = ""
    while time.time() < deadline:
        r = client.get(f"/api/agent/{session_id}")
        r.raise_for_status()
        branch = r.json().get("branch") or ""
        if branch:
            break
        time.sleep(0.5)
    if not branch:
        raise SystemExit("session has no branch after 30s")
    return session_id, branch


def stop_session(client: httpx.Client, session_id: str) -> None:
    client.delete(f"/api/agent/{session_id}")


def verify_wastebin(session_id: str) -> None:
    db = _home() / "state.db"
    conn = sqlite3.connect(db)
    wb = conn.execute(
        "SELECT session_id FROM wastebin WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    hist = _home() / "wastebin" / f"{session_id}.history.json"
    if wb is None:
        raise SystemExit(f"wastebin row missing for {session_id}")
    if not hist.is_file():
        raise SystemExit(f"missing history: {hist}")
    print(f"OK wastebin + history for {session_id} ({hist.stat().st_size} bytes)")


def run_agent_phase(
    client: httpx.Client,
    *,
    repo: Path,
    label: str,
    task: dict,
    prompt: str,
    target_status: str,
    timeout: float,
    keep_session: bool,
    expect_criteria: bool = True,
) -> None:
    print(f"\n--- {label} ---")
    print(f"task: {task['id']} {task['title']!r} (target={target_status})")

    session_id, branch = start_session(client, task_id=task["id"], prompt=prompt)
    print(f"session: {session_id}")
    print(f"branch: {branch}")

    ok, note, task_after = wait_for_task_status(
        client,
        repo=repo,
        branch=branch,
        task_id=task["id"],
        session_id=session_id,
        target_status=target_status,
        timeout=timeout,
    )
    if not ok:
        if not keep_session:
            stop_session(client, session_id)
        raise SystemExit(f"FAIL — {label}: {note}")
    print(f"OK {label}: {note}")

    if expect_criteria and not all_criteria_met(task_after):
        raise SystemExit(f"FAIL — {label}: not all acceptance criteria marked met")
    if expect_criteria:
        print(f"OK criteria met: {task_after.get('criteria_met')}")

    assert task_after.get("status") == target_status

    if keep_session:
        print(f"session kept live: {session_id}")
        return

    stop_session(client, session_id)
    print("OK session stopped")
    time.sleep(1)
    verify_wastebin(session_id)


def create_e2e_task(client: httpx.Client) -> dict:
    r = client.post(
        "/api/tasks",
        json={
            "title": E2E_TASK_TITLE,
            "description": (
                "Automated e2e smoke task. Add one header comment to "
                "src/color.ts, mark the criterion met, then move to done."
            ),
            "project": PLAYGROUND_PROJECT,
            "status": "open",
            "review_gate": "none",
            "acceptance_criteria": [E2E_CRITERION],
            "tags": ["e2e"],
        },
    )
    if r.status_code not in (200, 201):
        raise SystemExit(f"create e2e task failed: {r.status_code} {r.text}")
    return r.json()


def run(
    base: str,
    timeout: float,
    *,
    keep_session: bool,
    smoke_only: bool,
) -> None:
    token = _token()
    cookies = {"agent-knots-session": token}
    phase_timeout_smoke = min(SMOKE_PHASE_TIMEOUT, timeout)
    phase_timeout_review = min(REVIEW_PHASE_TIMEOUT, max(timeout - phase_timeout_smoke, 120))

    with httpx.Client(base_url=base, cookies=cookies, timeout=120.0) as client:
        print(f"target: {base}")
        print(f"home:   {_home()}")
        print(
            f"timeout: smoke={phase_timeout_smoke}s, review={phase_timeout_review}s"
            if not smoke_only
            else f"timeout: smoke={phase_timeout_smoke}s"
        )

        stopped = stop_playground_sessions(client)
        if stopped:
            print(f"stopped {stopped} stale playground session(s)")

        r = client.delete("/api/playground")
        print(f"reset playground: {r.status_code}", end="")
        if r.status_code == 200:
            body = r.json()
            wb = body.get("removed_wastebin", 0)
            print(f" (tasks={body.get('removed_tasks', 0)}, wastebin={wb})")
        else:
            print()

        r = client.post("/api/playground")
        if r.status_code not in (200, 201):
            raise SystemExit(f"create playground failed: {r.status_code} {r.text}")
        data = r.json()
        repo = Path(data["repository"])
        print(f"playground: seeded={data.get('seeded_tasks')} repo={repo}")
        if not repo.is_dir():
            raise SystemExit(f"repo missing: {repo}")

        smoke = create_e2e_task(client)
        run_agent_phase(
            client,
            repo=repo,
            label="smoke task (auto-done)",
            task=smoke,
            prompt=SMOKE_PROMPT,
            target_status="done",
            timeout=phase_timeout_smoke,
            keep_session=keep_session,
        )

        if smoke_only:
            print("\n=== PLAYGROUND AGENT E2E PASSED (smoke only) ===")
            return

        dark = find_playground_task(client, DARK_MODE_TITLE)
        if dark.get("status") not in ("draft", "open"):
            raise SystemExit(
                f"FAIL — {DARK_MODE_TITLE!r} expected draft/open, got {dark.get('status')!r}"
            )
        run_agent_phase(
            client,
            repo=repo,
            label="Dark mode (human review)",
            task=dark,
            prompt=DARK_MODE_PROMPT,
            target_status="review",
            timeout=phase_timeout_review,
            keep_session=keep_session,
        )

        manifest = repo / ".agent-knots" / "playground.yaml"
        if not manifest.is_file():
            raise SystemExit(f"missing manifest: {manifest}")
        print("OK manifest present")

    print("\n=== PLAYGROUND AGENT E2E PASSED ===")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Do not stop the session (for debugging a failed run)",
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run only the auto-done smoke task (skip Dark mode review phase)",
    )
    args = parser.parse_args()
    try:
        run(
            args.base_url,
            args.timeout,
            keep_session=args.keep_session,
            smoke_only=args.smoke_only,
        )
    except httpx.ConnectError:
        raise SystemExit(f"cannot connect to {args.base_url} — is the cockpit running?") from None


if __name__ == "__main__":
    main()
