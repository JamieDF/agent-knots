# Retrospective — where agent-knots actually is

**Date:** 2026-07-20
**Codebase:** ~6.0K src LOC (Python) + ~2.1K frontend LOC (TSX/TS), 171 Python
unit tests (106 at the start of this audit, +65 added same day covering the
fixes below), 43 Playwright e2e tests
**Goal:** honest self-audit — what's real, what's stubbed, what's untested,
where docs oversell the code

This supersedes the old Go-era `RETRO.md` (deleted in the Python rebuild
cleanup). Everything below was verified by reading the actual code, not by
re-reading docs.

---

## Fixed since this audit (same day, backend-fixes pass)

TUI-specific findings (items 3 and 4 under "Real bugs") were explicitly
deprioritized — GUI is getting a redesign, TUI isn't a current focus — so
left as-is. Everything else frontend-agnostic got fixed:

- **`delegate_task` ordering bug (Real bugs #1)** — fixed. The tool is now
  appended to `all_tools` before the `Agent` is constructed.
- **Dead `InProcessRuntime` (Real bugs #2)** — fixed. `InProcessRuntime.
  start()` now actually starts the agent task; `SessionManager.start()`
  goes through `create_runtime()` for both runtime types instead of
  special-casing subprocess. Also fixed a related bug this surfaced:
  `create_runtime()` only ever consulted the *global* runtime-type
  setting, ignoring a per-project override that had already been
  resolved by the caller — a project configured for `subprocess` could
  silently get `inprocess` instead if the global default differed.
- **TUI built-in tool toggle (Real bugs #3, backend half)** — fixed at the
  root: `ToolRegistry.list_builtin()`/`list_enabled()` now actually read
  the disabled-builtins file. This was framed as a TUI bug, but it's a
  `tools/registry.py` bug — it also silently broke the web Settings
  page's built-in tool toggle. Fixed for all surfaces, not just the TUI.
- **Unconfined shell sandbox (Security gaps #1)** — *improved, not fully
  solved*. Added real resource limits (CPU time + memory via
  `resource.setrlimit`) and process-group cleanup on timeout (the old
  code only killed the direct child, leaking any background processes a
  command spawned). Command-string-level path confinement was
  deliberately **not** attempted — regex/blocklist validation of
  arbitrary `shell=True` input is not real security and would create a
  false sense of safety. `sandbox_tools.py`'s module docstring now says
  this plainly. Real containment still needs the container runtime on
  the roadmap.
- **Custom tools bypassing the sandbox (Security gaps #2)** — fixed.
  `CustomTool.to_strands_tool()` and `ToolRegistry.list_enabled()` now
  thread a `cwd` through from `SessionManager.start()`'s resolved
  workspace directory, and custom tools go through the same resource-
  limited `run_confined()` helper as the sandboxed shell tool.
- **No acceptance-criteria enforcement (Security gaps #5)** — fixed as a
  hard block, per explicit decision. `Task.criteria_met` now tracks which
  criteria have been explicitly marked satisfied via the new
  `mark_criterion_met` tool/store method. `TaskStore._validate_transition`
  (used by both `set_status` and status-carrying `log_progress` calls —
  both paths, not just one) refuses a `done` transition until every
  criterion is marked met. The steering hook's keyword match stays
  advisory-only by design, so a fuzzy match can't quietly satisfy the
  gate. 12 new tests added in `tests/test_task/test_store.py`.

`SessionManager.start()` and `session/runtime.py` now have real test
coverage (`tests/test_session/test_manager.py::TestSessionManagerStart`,
`tests/test_session/test_runtime.py`) — 18 new tests covering exactly the
bugs above: delegate_task actually reaching the constructed `Agent`,
disabled built-ins actually being excluded, custom tools actually binding
to the session workspace, and `InProcessRuntime.start()` actually creating
the background task. None of it needs network — no `task_description` is
passed, so the in-process runtime never invokes the real agent loop.

### Second pass — remaining backend cleanup items

- **Auth duplication ("Real bugs #8")** — consolidated. `server.py`'s
  `auth_middleware` now uses `auth.py`'s `verify_token()` (constant-time
  compare) instead of plain `==`/`!=` on the cookie, `?token=`, and login
  form — the old code wasn't timing-attack-safe despite that helper
  existing specifically to prevent it. Added `Authorization: Bearer`
  support to the actual middleware (previously that path only existed in
  the unused `Auth.require()`). Removed `Auth.require()` itself — it
  assumed a `Depends()`-per-route architecture the app doesn't use, so
  keeping it around as a second, unreachable auth implementation was the
  actual problem, not a fix worth preserving. `login_post` now calls
  `auth.set_cookie_redirect()` instead of duplicating the cookie-setting
  code inline. Fixed the broken `cockpit_url` (`@property` that couldn't
  accept the `host`/`port` args it declared) by making it a plain method.
  Also fixed a pre-existing test-isolation gap while adding coverage
  here: `tests/test_web/test_server.py` had no `AGENT_KNOTS_HOME`
  override, so it was reading/writing the *real* user's cockpit token
  file. Added an `agent_knots_home` fixture; 8 new tests cover query
  token, cookie, Bearer header, and the login POST flow, including wrong-
  token rejection for each.
- **`validate_task_output` ("Wired in but never called")** — wired up, and
  moved from `session/features.py` to `task/tools.py` (it's task-domain
  validation, not really a session feature — the old location was just
  where it happened to get written). Now runs inside `create_task` and
  `update_task` before constructing a `Priority`/`TaskStatus`, turning
  what used to be an uncaught `ValueError` on invalid input into a
  structured `{"error": ...}` tool response. 12 new tests in
  `tests/test_task/test_tools.py`.
- **`save_checkpoint`/`load_checkpoint` ("Wired in but never called")** —
  removed rather than wired up. No call site anywhere (no CLI command, no
  API route, nothing ever resumed from a checkpoint), `inject_memory`
  already covers cross-session continuity more robustly (structured
  progress-log entries vs. an untyped session-data dict), and real
  session/agent-state resume would need to serialize actual conversation
  history — a real feature to design later, not scaffolding worth
  reviving as-is. See `docs/strands-features.md`'s new "Removed" section.
- **`WorkspaceSandbox`'s dead config (Security gaps #3)** — resolved per
  field, not uniformly. `max_output` (shell) and `max_file_size` (editor)
  are now real: `run_confined()` truncates stdout/stderr past
  `max_output`, and the sandboxed editor rejects writes past
  `max_file_size` before touching disk. `allowed_urls` was **removed**
  rather than enforced — there's no URL-fetching tool anywhere in
  `DEFAULT_TOOLS` for it to gate, and even if there were, the shell tool
  already has unrestricted network access (see gap #1), so a URL
  allowlist on one hypothetical future tool wouldn't have been meaningful
  protection. 14 new tests in `tests/test_sandbox_tools.py` (previously
  zero coverage for this whole module).

---

## Headline

The **vault, task store, project store, and Playwright e2e suite are
genuinely solid** — real crypto, real CRUD, real end-to-end tests against a
live server and a live LLM session. The **rest of the system has a
consistent pattern**: features are implemented and wired in, but silently
broken at one seam, or implemented and never actually connected to
anything, or implemented with zero test coverage. Nothing is faked outright
— there's no literal `TODO`/`NotImplementedError` scaffolding hiding
behind a "✅ Done" claim (with one exception, the TUI's "add custom tool").
The bugs are subtler: an append-after-construct ordering mistake, a
disabled-flag that's read in one place and ignored in another, a field the
frontend sends that the backend model doesn't have.

---

## What's solid

1. **Vault.** AES-256-GCM + argon2id, per-entry key derivation, injection
   template CRUD, append-only audit log — all real, all tested (50 unit
   tests across crypto + store, including tamper detection and wrong-key
   failure paths).
2. **Task store.** Full YAML-backed CRUD, progress logs, steps, terminal-
   status protection — tested with real error-path coverage.
3. **Project store.** Full CRUD, now wired to both the web API and the CLI.
4. **Playwright suite (43 tests).** Genuine end-to-end tests against a
   **live server** on `127.0.0.1:8090` with a **real token** and, for
   several tests, a **real running LLM session** (e.g. sends an actual
   prompt, asserts on live model output). Not mocked, not render-only smoke
   tests for the most part. This is the strongest test coverage in the
   whole system — on the outer layer, ironically, not the backend units.
5. **Token/cost tracking** reads real usage from model response metadata
   (`hooks.py`), not the old hardcoded estimate — though cost is still a
   flat $0.30/1M rate regardless of actual provider/model.
6. **Provider resolution precedence** (CLI flag → env var → settings file)
   matches the docs exactly.

---

## Real bugs

1. **`delegate_task` is likely never actually usable.** In
   `session/manager.py`, `make_delegate_tool` is appended to the tool list
   *after* the Strands `Agent` was already constructed with the earlier
   list. Multi-agent delegation is wired into every session per the code
   path, but the tool probably never reaches the agent. Zero tests would
   have caught this.
2. **`InProcessRuntime` is dead code.** `SessionManager.start()` never
   constructs it — non-subprocess sessions run `_run_agent` directly,
   bypassing the `SessionRuntime` abstraction entirely. The "two runtimes"
   architecture description (mine included, in `docs/architecture.md`) is
   misleading; only the subprocess path is real.
3. **TUI tool-manager toggle is broken for built-in tools.** Disabling a
   built-in via the TUI writes `disabled_tools.yaml`, but
   `ToolRegistry.list_builtin()`/`list_enabled()` hardcode `enabled=True`
   and never read that file. The UI shows it as enabled, and the agent
   still gets the tool — toggling a built-in tool does nothing. Only
   custom-tool toggling actually works.
4. **TUI "add custom tool" is a literal placeholder** — `self.notify(
   "...coming soon...")`.
5. **Kanban board silently drops tasks.** `TaskStatus` has 8 values;
   `Board.tsx` only renders 6 columns. Tasks in `blocked` or `abandoned`
   status have no column and disappear from the board (the Tasks list view
   handles all 8 correctly — this is Board-specific).
6. **Task description edits don't persist.** `TaskDetail.tsx`'s edit modal
   sends `description` in the update payload; the server's
   `UpdateTaskRequest` Pydantic model doesn't have that field, so it's
   silently dropped. Editing a task's title/status works; editing the
   description does not.
7. **SSE has no fan-out.** Each session's events live in a single
   `asyncio.Queue`; if two browser tabs open the event stream for the same
   agent, they race for `queue.get()` and each event goes to only one of
   them. Not a crash, just silent event loss for the second tab.
8. **Auth has two divergent implementations.** `auth.py`'s real `Auth`
   class (with `Authorization: Bearer` support) is dead code — `server.py`
   reimplements its own inline cookie/`?token=` middleware instead of using
   it. `auth.py`'s `cockpit_url` is additionally just broken (a `@property`
   that can't accept the `host`/`port` args it's written to take).

---

## Security-relevant gaps

1. **The sandboxed shell tool doesn't actually confine shell commands.**
   `make_sandboxed_shell` runs `subprocess.run(command, shell=True, cwd=
   workspace, ...)` with **no validation of the command string at all**.
   `cd /`, absolute paths, `../../..`, `rm -rf /`, `curl` — none of it is
   blocked. Only a 60s timeout is enforced. Path confinement (via
   `_resolve()`, which does correctly catch symlink escapes) only applies
   to the **editor** tool, not shell.
2. **Custom tools bypass the sandbox entirely.** They run via
   `subprocess.run` with **no `cwd` set at all** — they execute in the
   server process's actual working directory, ignoring whatever workspace
   is configured for the session.
3. **`WorkspaceSandbox`'s own limits are dead config.** `allowed_urls`,
   `max_output`, `max_file_size` are all defined fields, never read
   anywhere in the codebase. No network allowlist, no output size cap is
   actually enforced despite the dataclass implying there is one.
4. **Tool-use confirmation is globally bypassed for every session** via
   `BYPASS_TOOL_CONSENT=true` + monkeypatched `get_user_input`. This is
   an intentional design choice (agents run non-interactively) but it's
   all-or-nothing — no per-tool allowlist — and has zero test coverage.
5. **No acceptance-criteria enforcement.** An agent can call
   `update_task_status(..., "done")` with unmet acceptance criteria and
   nothing stops it. The only related mechanism, the steering hook, does a
   keyword match and *logs* a note — it never blocks the transition. Its
   own docstring calls it a placeholder ("production would use LLM
   evaluation"). README's task-system description implies gating that
   doesn't exist.
6. **`?token=` query-param auth** authorizes any `/api/*` request if the
   token leaks via browser history, referrer headers, or logs. Intentional
   tradeoff for `EventSource` (which can't set custom headers), but worth
   knowing if you ever expose the cockpit beyond localhost.

---

## Wired in but never tested, or wired in but never called

> **Update:** the first two items below are resolved — see "Second pass"
> above. `save_checkpoint`/`load_checkpoint` were removed;
> `validate_task_output` was wired into `create_task`/`update_task`.

- **`save_checkpoint`/`load_checkpoint`** — fully implemented, listed as
  "✅ Integrated" in `docs/strands-features.md`, but **never called from
  anywhere else in the codebase**. Orphaned.
- **`validate_task_output`** — defined, never called.
- **`register_steering_hook`** (memory injection's sibling) — actually
  wired in and does run, but only does advisory keyword matching (see
  security gaps above).
- `GET /api/tools/{name}` and `GET /api/health` — real endpoints, not
  called by any frontend code. Health-check is presumably meant for
  external monitoring, so that one's fine to leave orphaned from the UI.
- A near-duplicate `ToolManager.tsx` view exists alongside `Settings.tsx`'s
  tools tab — not confirmed whether it's reachable from the router; likely
  a leftover from an earlier layout.

---

## Test coverage: the real gap

> **Update:** `SessionManager.start()` and `session/runtime.py` are no
> longer zero-coverage — see "Fixed since this audit" above. The rest of
> this section (as originally written) still stands.

**`SessionManager.start()` — the ~200-line method that resolves the
provider, builds the system prompt, assembles tools, wires the sandbox,
registers hooks, and constructs the Strands `Agent` — has zero test
coverage.** No test, mocked or real, ever calls it. Every bug above that
lives inside that method (the delegate-tool ordering bug, the dead
`InProcessRuntime` branch) would have been caught by a single test that
actually started a session with a fake/mock model.

Zero test coverage, full stop, for: `cockpit/tui/app.py`,
`cockpit/web/auth.py`, `session/runtime.py`, `session/worker.py`,
`session/features.py`, `hooks.py`, `intervention.py`, `isolation.py`,
`sandbox_tools.py`, `tools/registry.py`, `project/store.py`, `cli/main.py`
(including the `project`/`vault template` commands added this session),
`provider.py`, `settings.py`.

`test_web/test_server.py` exists (116 lines) but only covers unauthenticated
paths — health check, login redirect, login page render, HTML-escaping in
`format_event_html`. None of the 26 real API routes' authenticated behavior
is tested.

By contrast, `test_vault/*`, `test_task/test_store.py`, and the Playwright
suite are genuinely thorough, including error paths.

---

## Doc/reality mismatches to fix

- **README.md says "Playwright e2e tests (30)"** — the actual number,
  confirmed by both the CHANGELOG and the test file itself, is **43**.
- `docs/architecture.md` (written during this session's cleanup) describes
  `InProcessRuntime`/`SubprocessRuntime` as two symmetric runtime
  implementations — needs a correction noting the in-process path bypasses
  the `SessionRuntime` abstraction entirely.
- `docs/strands-features.md` marks checkpoint and structured-output
  validation "✅ Integrated" — they're implemented but not wired to
  anything; should be re-labeled (e.g. "implemented, unused").
- `settings.py`'s `default_mode` field is referenced in code but
  undocumented anywhere in README/quickstart.

---

## If I were prioritizing the next two weeks

1. **Write one test that actually starts a session** (mock the model
   client) — this single test would surface/prevent most of the bugs
   above and is the highest-leverage thing missing.
2. **Fix the shell sandbox** — either add real command validation or be
   honest in docs that "sandbox" currently only means "confined cwd for
   the editor tool, nothing else."
3. **Fix custom tools' missing `cwd`** — one-line fix, currently a
   silent full bypass of workspace isolation.
4. **Fix the built-in tool toggle** in `list_builtin()`/`list_enabled()` —
   small, contained, currently makes a whole TUI feature a no-op.
5. **Decide whether acceptance-criteria gating is a real product
   requirement** — if yes, it needs actual enforcement; if the steering
   hook's advisory-only behavior is the intended design, the docs need to
   stop implying otherwise.
