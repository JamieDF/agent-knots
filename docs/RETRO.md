# Retrospective — where agent-knots actually is

**Date:** 2026-07-23 (supersedes the 2026-07-20 audit below)
**Codebase:** ~7.7K src LOC (Python) + ~5.1K frontend LOC (TSX/TS), 350 Python
unit tests, 74 Playwright e2e tests
**Goal:** honest self-audit — what's real, what's stubbed, what's untested,
where docs oversell the code

This supersedes the old Go-era `RETRO.md` (deleted in the Python rebuild
cleanup) and refreshes the 2026-07-20 Python-era audit below it. Everything
in this update was re-verified by reading the actual current code, not by
trusting the previous audit's claims — several had already been fixed by
the time this pass started.

---

## What changed since the 2026-07-20 audit

The web cockpit went through a full redesign ("Atelier" — see
`CHANGELOG.md`'s `[Unreleased]` section and `roadmap.md`), plus several
rounds of real-usage bug fixing. Every "Real bug" and most "Security gap"
findings from the original audit are now fixed; see each section below for
what's actually still true today.

Headline: the pattern the original audit found — "implemented and wired
in, but silently broken at one seam, or never actually connected to
anything" — has mostly been closed. What's left is smaller and more
specific: one still-orphaned duplicate UI, a couple of modules with no
*dedicated* test file (though several are now exercised indirectly through
much larger integration-style tests), and security tradeoffs that are
documented rather than silently present.

---

## What's solid

1. **Vault.** AES-256-GCM + argon2id, per-entry key derivation, injection
   template CRUD, append-only audit log — real, tested, and now has a full
   web UI (a Settings section) alongside the CLI, closing what was
   previously the single biggest web-GUI gap.
2. **Task store.** Full YAML-backed CRUD, progress logs, steps, terminal-
   status protection, and a real review-gate enforced on the `done`
   transition (not just displayed) — tested with real error-path coverage.
3. **Project/workspace store.** Full CRUD wired to web API, CLI, and now a
   real edit + archive/unarchive UI in Settings (previously create+delete
   only).
4. **Task editing.** Title, description, priority, tags, acceptance
   criteria, and steps are all editable after creation from the web UI —
   previously description/tags/criteria edits were silently dropped by
   `UpdateTaskRequest` having no matching fields.
5. **Criteria completion.** A human can mark an acceptance criterion met
   or unmet directly from Task Detail (`POST /api/tasks/{id}/criteria/
   toggle`) — previously `mark_criterion_met` was agent-tool-only, and
   "done" is hard-gated on this.
6. **SSE fan-out.** `Session._broadcast()`/`subscribe()` gives every
   connected browser tab its own subscriber queue seeded from a shared
   event history — previously a single `asyncio.Queue` meant two tabs
   watching the same agent raced for events and one silently missed some.
7. **Playwright suite (69 tests).** Genuine end-to-end tests against a
   live server with a real token; several exercise a real running LLM
   session. Still the strongest test coverage in the system.
8. **`test_web/test_server.py` (99 tests, 1065 lines).** No longer
   unauthenticated-paths-only — covers cookie/query-token/Bearer auth,
   most of the real API routes, including the newer review-gate, criteria-
   toggle, and workspace-archive endpoints.
9. **Token/cost tracking** reads real usage from model response metadata —
   cost is still a flat rate, see Security-relevant gaps.
10. **Auth.** `auth.py`'s `Auth` class and `verify_token()` (constant-time
    compare) are the single implementation used everywhere — the old
    dead-code duplicate (`Auth.require()`, a broken `cockpit_url`
    `@property`) is gone.
11. **Real interactive terminal.** A genuine PTY (`pty.fork()`) behind a
    websocket, rendered with xterm.js — real shell, real cwd, real
    running processes, not a read-only output log. Stays connected across
    Agent Thread tab switches.
12. **Background process execution.** `sandbox_tools.run_background()` +
    the shell tool's `background=true` — an agent can start a dev server
    or watcher without the tool's timeout killing it, tracked per-session
    and cleaned up (including reaping the zombie, not just sending
    SIGKILL) when the session ends.
13. **Browser tab.** A real multi-tab in-panel browser (address bar,
    open/close tabs) replacing the old static "coming soon" Preview
    placeholder — any URL the agent mentions in chat opens in a new tab.

---

## Real bugs (fixed since 2026-07-20)

All eight items the original audit found here are now fixed, verified
directly against current code. Items 9+ below are bugs found and fixed in
a later same-day pass, after real usage surfaced them — not part of the
original 2026-07-20 audit:

1. ~~`delegate_task` never reaches the agent~~ — fixed.
   `make_delegate_tool` is appended to `all_tools` before `Agent(...)` is
   constructed (`session/manager.py`), with a comment explaining why order
   matters.
2. ~~`InProcessRuntime` is dead code~~ — fixed. `start()` actually creates
   the background task; `SessionManager.start()` goes through
   `create_runtime()` for both runtime types.
3. ~~TUI built-in tool toggle is broken~~ — fixed. `ToolRegistry.
   list_builtin()`/`list_enabled()` read the disabled-builtins file for
   real now.
4. **TUI "add custom tool" is still a placeholder.** Unchanged —
   explicitly deprioritized (TUI isn't a current focus vs. the web
   redesign). `app.py`: `self.notify("Custom tool creation via TUI coming
   soon. Use the web cockpit to add tools.")`.
5. ~~Kanban board silently drops tasks~~ — fixed, and more thoroughly than
   just "add 2 columns": stages are now a configurable store (Workflows
   screen) with all 8 statuses covered; `blocked`/`planned` surface as
   card badges within their parent column instead of needing their own.
6. ~~Task description edits don't persist~~ — fixed, see "What's solid" #4.
7. ~~SSE has no fan-out~~ — fixed, see "What's solid" #6.
8. ~~Auth has two divergent implementations~~ — fixed, see "What's solid" #10.
9. ~~An agent could self-approve its own review-gated work~~ — fixed.
   `update_task_status('review')` then `update_task_status('done')`
   back-to-back in one turn used to trivially satisfy the "must be in
   review" check with zero human oversight, worst with no acceptance
   criteria set (nothing else blocked it either). `_validate_transition`
   is now actor-aware: only the web's human-driven PATCH route passes
   `actor="human"`; every agent tool call defaults to `actor="agent"` and
   is refused past `review`.
10. ~~Composer "Stop" killed the whole session, not just the current
    turn~~ — fixed. Cancelling a session's asyncio task always broadcast
    `ENDED`, locking the composer into replay mode, so the only way to
    interrupt one bad tool call was to end the session outright and start
    a new one. `Session.cancel(end_session=False)` (used by the new
    `interrupt()`/`POST /api/agent/{id}/interrupt`) now reports a
    `STATE_CHANGE` instead — the session survives, send another message
    to continue.
11. ~~`RLIMIT_AS` made Node/Vite/npm crash outright under the sandboxed
    shell~~ — fixed by removing the cap (kept the CPU-time cap). V8
    reserves several GB of *virtual address space* upfront for its
    sandbox tables regardless of actual memory used; any `RLIMIT_AS` cap
    small enough to matter (the sandbox used 512MB) crashed Node
    immediately with `Fatal process out of memory:
    SegmentedTable::InitializeTable` before a single line of JS ran — so
    every `npm`/`vite`/`webpack` command an agent tried failed outright,
    real memory pressure or not. Reproduced the exact crash with the old
    limit before removing it, to confirm the diagnosis.
12. ~~The workspace switcher dropdown never showed a newly-created
    workspace without a full page reload~~ — fixed. `WorkspaceSwitcher.tsx`
    fetched the workspace list once on mount and never again; it now
    refetches every time the dropdown opens, matching the pattern
    `NewSessionDialog.tsx` already used.
13. ~~The printed one-click cockpit URL bounced to the login page~~ —
    fixed. The `?token=` query-param login only checked `/api/*` paths;
    the printed URL's path is `/`, so it fell through to the login page
    instead of logging in directly. Now accepted on any path, setting the
    cookie and redirecting to a clean (token-stripped) URL.

Only #4 remains from the original audit, and it's a deliberate non-fix,
not an oversight.

---

## Security-relevant gaps

1. **The sandboxed shell tool still doesn't validate the command string.**
   `make_sandboxed_shell` runs `subprocess.run(command, shell=True, ...)`
   with no blocklist/regex on the command itself — `cd /`, absolute
   paths, `rm -rf /` are all possible. This is unchanged **by design**:
   the module's docstring now says plainly that command-string validation
   for arbitrary `shell=True` input isn't real security. What *did*
   improve: real resource limits (`resource.setrlimit` for CPU time and
   memory) and process-group cleanup on timeout (`os.killpg`, so a
   background process a command spawned doesn't leak past the timeout).
   Real containment still needs the container runtime on the roadmap.
2. ~~Custom tools bypass the sandbox entirely~~ — fixed. `CustomTool.
   to_strands_tool()` threads `cwd` through from the resolved workspace
   and runs via the same `run_confined()` helper as the sandboxed shell.
3. **`WorkspaceSandbox`'s dead config** — resolved per field, not
   uniformly. `max_output` and `max_file_size` are real (verified: shell
   output truncation and editor write-size rejection both fire). `allowed_
   urls` was removed rather than enforced — there's no URL-fetching tool
   in `DEFAULT_TOOLS` for it to gate.
4. **Tool-use confirmation is still globally bypassed** via
   `BYPASS_TOOL_CONSENT=true` + monkeypatched `get_user_input`. Unchanged,
   intentional (agents run non-interactively), still all-or-nothing with
   no per-tool allowlist.
5. ~~No acceptance-criteria enforcement~~ — fixed, see "What's solid" #2/#5.
6. **`?token=` query-param auth** still authorizes any `/api/*` request if
   the token leaks via browser history/referrer/logs. Unchanged,
   intentional tradeoff for `EventSource` (can't set custom headers) —
   worth knowing if you ever expose the cockpit beyond localhost.

Two of six gaps closed; the remaining four are either deliberate,
documented tradeoffs (1, 4, 6) or partially mitigated (3).

---

## Wired in but never called, or never tested

- ~~`save_checkpoint`/`load_checkpoint`~~ — removed rather than wired up
  (no call site ever existed; `inject_memory` covers cross-session
  continuity more robustly). See `docs/strands-features.md`'s "Removed"
  section.
- ~~`validate_task_output`~~ — fixed, wired into `create_task`/`update_task`.
- **`register_steering_hook`** — still advisory-only by design (keyword
  match logs a suggestion, never marks a criterion itself). Not a bug —
  the enforcement gate only respects explicit `mark_criterion_met` calls.
- **`GET /api/tools/{name}`** — still a real route, still never called by
  any frontend code (the frontend only PATCHes/DELETEs/toggles by name,
  never fetches single-tool detail).
- **`GET /api/health`** — still unused by the frontend; fine to leave
  orphaned from the UI, presumably meant for external monitoring.
- ~~`ToolManager.tsx` was a genuine orphaned duplicate~~ — fixed. Deleted
  along with its `/tools` route (redirects to `/settings#tools` now,
  matching the `/vault` -> `/settings#vault` pattern) as part of the full
  codebase review — see `docs/CODE_REVIEW.md`.
- ~~`SubprocessRuntime` was broken~~ — deleted rather than fixed.
  `session/worker.py`'s `_read_events` (and `runtime.py`'s
  `SubprocessRuntime._read_events`) still referenced `session._events.put(
  ...)`, an attribute `Session` no longer has since the SSE fan-out fix
  replaced the single `_events` queue with `_subscribers`/`_history`/
  `_broadcast()` — would have raised `AttributeError` the moment a
  subprocess-runtime session tried to emit an event, uncaught by any test
  since the default runtime is `inprocess`. Its own event-chunk parser had
  also independently drifted from the fixed one in `session/manager.py`.
  Fixing both bugs and then maintaining two parsers in sync going forward,
  for a mode nothing selected by default and that never worked when
  selected, wasn't worth it — deleted `session/worker.py` and
  `SubprocessRuntime` entirely; `create_runtime()`/`set_runtime_type()`
  now silently fall back to in-process for any unrecognized runtime value
  (including a pre-existing "subprocess" saved before the removal), so
  upgrading doesn't break an existing workspace/settings file. Real
  process isolation is still wanted — see the container-runtime roadmap
  item — just not this implementation.

---

## Test coverage

**Real, substantial improvement since 2026-07-20** — `test_web/
test_server.py` alone grew from unauthenticated-paths-only to 99 tests
covering real authenticated routes, and `test_session/test_manager.py`
grew to 39 tests including a `TestSessionManagerStart` class that
exercises the actual `SessionManager.start()` path (provider resolution,
system prompt assembly, tool set, sandbox wiring, hooks, `Agent`
construction) rather than mocking it away — the exact method the original
audit called out as having zero coverage.

That said, several modules still have **no dedicated test file** —
`cockpit/tui/app.py`, `cockpit/web/auth.py` (indirectly covered via
`test_server.py`'s auth tests, which exercise `verify_token()` but not
`auth.py` in isolation), `session/worker.py`, `session/features.py`
(indirectly covered via `test_manager.py`'s session-start tests),
`hooks.py`, `intervention.py`, `isolation.py` (all three indirectly
exercised the same way), `tools/registry.py` (indirectly covered via
`test_server.py`'s tool-toggle tests), `project/store.py` (indirectly
covered via `test_server.py`'s workspace tests), `cli/main.py`,
`provider.py`, `settings.py`. "No dedicated file" isn't the same as "zero
coverage" anymore for most of these — the integration-style tests through
`SessionManager.start()` and the web API genuinely exercise them — but a
bug isolated to one of these modules in a code path the integration tests
don't happen to hit still wouldn't be caught by a focused unit test.

---

## Doc/reality mismatches

The 2026-07-20 audit's four mismatches are now resolved as part of this
same documentation pass:

- ~~README says "43" but code has more~~ — README's test counts (and this
  file's) are current as of this audit.
- ~~`docs/architecture.md` describes `InProcessRuntime` as dead code~~ —
  fixed to describe both runtimes as real, matching "Real bugs" #2 above.
- `docs/strands-features.md`'s "✅ Integrated" labels for checkpoint and
  structured-output validation — checkpoint was removed (see "Wired in"
  above) rather than relabeled, since it no longer exists to mislabel;
  structured-output validation is genuinely wired in now, so its label is
  accurate as-is.
- `settings.py`'s `default_mode` field is still not exposed in the
  Settings UI or documented in the quickstart — this one's still open,
  low priority (manual YAML edit works).

---

## If I were prioritizing the next two weeks

Both items that topped this list in the previous pass — the
`SubprocessRuntime` bug and the `ToolManager.tsx` duplicate — are fixed
now (deleted, in both cases; see above). Also fixed since: a real bug
found by the same review, where the mode-gating intervention handler
used method names that don't match the Strands SDK's base class, so it
was never actually registered — see `docs/CODE_REVIEW.md` for the fix
and the wider cleanup pass it kicked off (dead code removed, several
smaller real bugs fixed, `intervention.py` now has dedicated tests).

1. **Container runtime** — still the biggest real security gap (#1
   above), and it's already on the roadmap. With `SubprocessRuntime`
   gone, this would be the first real *process*-isolated runtime rather
   than a second implementation to keep in sync with the first.
2. **Fill in `default_mode`** in the Settings UI, or explicitly document
   it as YAML-only if that's the intended long-term answer.
3. **Consider a targeted unit test** for `hooks.py` specifically — still
   exercised only indirectly today (via `SessionManager.start()`'s
   integration tests), unlike `intervention.py` which now has its own.
4. **File splits flagged by the review** (`server.py`, `AgentThread.tsx`,
   `Settings.tsx`, `cli/main.py`) — real maintainability value, sized as
   dedicated work rather than a drive-by; see `docs/CODE_REVIEW.md` for
   the concrete boundaries proposed for each.
