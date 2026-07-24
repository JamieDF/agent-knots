# Code Review — 2026-07-23 / 2026-07-24

Full-codebase review after a long stretch of fast, live feature work. Five
parallel reviews covering backend web/TUI, backend session/runtime, backend
data layer + CLI, the two biggest frontend files, and the rest of the
frontend — plus direct verification (reading the actual Strands SDK source)
of the most serious finding. This was a punch list, not a narrative;
checked off as items got fixed on the `cleanup/code-review` branch (a
separate git worktree, so the live server on `main` was never touched
while this was in progress).

**Status: everything on this list is done**, including the four large
file splits, the `FormDialog` extraction, and every item that had been
filed under "Lower priority / polish" — see "What actually shipped" at
the end for the full commit list. Every fix was verified against the
real test suite (389 Python tests, up from 335 at the start of this
file's own creation) and, for anything touching rendered UI or live
process behavior, against a real running instance across six separate
full-suite Playwright passes — not just "tests pass."

---

## 🔴 Real bugs currently shipping — all fixed

- [x] **Mode gating (Assume/Relinquish, Reviewer/Security) does nothing.**
  Fixed by renaming the four `on_*`-prefixed methods in
  `intervention.py` to match Strands' actual base-class names. Landed
  together with a larger redesign (the Autonomous toggle) that also
  narrowed which modes actually deny tool calls — see `docs/RETRO.md`
  and `docs/architecture.md`'s "Autonomous toggle" section for the full
  story; `assistant` mode no longer denies tools at all (that turned
  out not to be the wanted behavior), only `reviewer`/`security` do.
  Regression tests in `tests/test_intervention.py` assert the hook
  actually gets registered with Strands' `HookRegistry`, not just that
  the method returns the right value when called directly — that
  distinction is exactly what let the original bug hide.

- [x] **CLI `task update` silently unassigns a task on every call that
  omits `--assign`.** Fixed: `assign` now defaults to `None`. New
  `tests/test_cli/test_task_update.py` (previously no CLI test file
  existed at all).

- [x] **`SubprocessRuntime` was fully broken.** Deleted rather than
  fixed. `session/worker.py` and the `SubprocessRuntime` class are gone;
  `create_runtime()`/`set_runtime_type()` silently fall back to
  in-process for any unrecognized runtime value (including a
  pre-existing `"subprocess"` saved before the removal), verified live
  that a workspace with that value still starts a working session
  instead of crashing. The "Subprocess" option was also removed from
  the workspace runtime dropdown — it was a real, selectable, broken UI
  choice.

- [x] **Delegated sub-agent threads had the same event-fragmenting bug
  already fixed for the main thread.** Fixed: extracted the
  dedup/merge/accumulate logic into a shared `reduceEvent()` used by
  both the top-level thread and `DelegateSubThread`.

- [x] **Tool-call results always rendered green, regardless of success or
  failure.** Fixed one level deeper than it first looked: the backend
  never actually populated `Event.tool_result` for `TOOL_RESULT` events
  in the first place (only the free-text `message`), so there was no
  `exit_code`/`error` for the frontend to branch on. Now populated from
  Strands' own tool-agnostic `status` field ("success"/"error") — works
  for the shell tool's exit code as much as the editor/calculator/task
  tools, none of which have a real exit code.

---

## Dead code — all resolved

- [x] `views/ToolManager.tsx` + its `/tools` route — deleted. `/tools`
  now redirects to `/settings#tools`, matching the existing `/vault` ->
  `/settings#vault` pattern.
- [x] `api.ts`'s `updateTool()` — deleted.
- [x] `primitives/StatusDot.tsx`/`PriorityLabel.tsx` — deleted.
- [x] Unused Python imports across `server.py`, `session/manager.py`,
  `cli/main.py`, `settings.py` — removed. Also ran `ruff check --select
  F401` across the *whole* `src/` tree (not just the files the original
  review covered) and cleaned up what it found beyond that scope too:
  `cockpit/tui/app.py`, `hooks.py` (also fixed a stale unresolvable
  `"Session"` string type-hint while there), `policies/models.py`.
- [x] `settings.py`'s `is_configured()` — deleted (dead duplicate of
  `provider.py`'s `ProviderConfig.is_configured`).
- [x] `RolesStore.get()` — **not deleted.** Re-verified before acting on
  the finding and it turned out to have real, dedicated test coverage
  (`tests/test_workflows/test_store.py`) — a good example of why "no
  call site in production code" isn't the same as "no call site
  anywhere" for a review finding. Left alone.
- [x] `ToolInfo.id` — deleted (pure alias for `.name`, never read).
- [x] `EventType.PROGRESS` — deleted (genuinely zero producers or
  consumers). `EventType.BLOCKER` — **kept, not deleted.** It has real,
  working consumers already (the frontend's `blocker`/`ask` event-row
  branch, the TUI's pattern-match) waiting on a producer that was never
  built — that's a half-built feature, not dead code, and deleting it
  would have thrown away working rendering code for no reason. Added a
  comment on the enum member explaining its state.
- [x] `SessionManager.__init__`'s `sessions_dir`/`vault` fields —
  **left alone**, deliberately. They're genuinely unused, but dropping
  the constructor params touches every `SessionManager(...)` call site
  (including throughout the test suite) for zero behavior change — not
  worth the diff size/risk for this specific item.
- [x] Dead SSE `onClose`/`'close'` handling — removed from `sse.ts` and
  `AgentThread.tsx`. The backend never emitted a named `close` event;
  the real end-of-session signal (a `type: "ended"` event) was already
  handled through the normal path.

---

## Redundancy — all extracted

**Backend — done:**
- [x] The ~17 (turned out to be ~14 once the multi-exception/mixed-logic
  handlers were correctly excluded) near-identical
  `try/except ValueError -> HTTPException` blocks in `server.py` — new
  `@raises_as(status_code)` route decorator (now in `cockpit/web/
  decorators.py`). Verified against a real FastAPI app first that
  `functools.wraps` preserves the signature FastAPI needs for parameter
  injection (`inspect.signature()` follows `__wrapped__`) before
  applying it broadly. The handlers with real multi-step logic (`POST
  /api/sessions`, `PATCH /api/tasks/{id}`'s status branch) were left as
  plain `try/except` — they don't fit the "whole handler is one risky
  call" shape the decorator is for.
- [x] Duplicated agent-serialization dict (`list_agents`/`get_agent`) —
  new `_agent_to_response()` helper (now in `routes/agents.py`),
  matching every other domain's existing `_x_to_response()` pattern.
- [x] Atomic YAML write/read boilerplate — new `yamlfile.py`
  (`atomic_write_yaml()`/`safe_read_yaml()`), adopted by `task/store.py`,
  `project/store.py`, `settings.py`, `tools/registry.py`,
  `workflows/store.py`. Also centralizes chmod(0o600), previously
  applied inconsistently. `vault/store.py` **deliberately left alone**
  — it's JSON, not YAML, and the single most security-sensitive store
  in the codebase; not worth generalizing the helper into a
  format-agnostic one just to shave a few lines off the highest-risk
  file.
- [x] `update_task`'s per-field redundant writes — now mutates the
  in-memory task across all the plain content-field checks and writes
  once at the end. `status` and `assign` stay their own store calls
  (both `TaskStore.set_status()`/`.assign()` re-fetch from disk
  themselves) — kept first and last respectively so each still sees
  whatever the other has already persisted. Regression test locks this
  in, verified live with curl against a running server too.
- [x] Cross-file duplicate tool-toggle branching (`server.py` /
  `cockpit/tui/app.py`) — new `ToolRegistry.toggle()`. Along the way,
  fixed a latent TUI-only bug: its copy of the branching didn't check
  built-in membership before assuming a name was one, so toggling a
  genuinely nonexistent tool there silently no-opped instead of
  raising like the web route did — both now share the web route's
  stricter, correct behavior.
- [x] `task/store.py` vs `project/store.py`'s shared CRUD boilerplate —
  **evaluated, deliberately left alone.** Re-read both stores in full:
  the actual overlap is a thin ~25-line skeleton (`__init__`/`_path`/
  `create`/`get`/`delete`, the "check exists, else raise ValueError"
  pattern). Everything else genuinely differs — `TaskStore.list()` has
  real filtering/sorting business logic with a different signature
  than `ProjectStore`'s trivial no-args list; `_save`/`_load` are
  irreducibly different serialization; and the ~300 lines of
  `TaskStore`'s actual domain logic (`set_status` + its
  `_validate_transition` state machine, `log_progress`, `assign`,
  `mark_criterion_met`, `unmet_dependencies`, `add_step`, `_must_get`)
  has zero counterpart in `ProjectStore` at all. A generic base class
  would save ~25 lines at the cost of a shared abstraction for exactly
  two consumers, one of which barely uses it beyond create/get/delete
  anyway — a premature-abstraction trade, not a genuine simplification.

**Frontend — done:**
- [x] `Field`/`inputStyle` duplicated across 6 files — new
  `primitives/Field.tsx`, adopted by all 6. `FolderPicker.tsx`'s own
  `inputStyle` deliberately left alone — different layout context and
  font, not just a copy-paste duplicate.
- [x] `timeAgo`/`rel` duplicated 3× — new `lib/format.ts`.
- [x] `Workflows.tsx`'s hand-rolled dialog overlay — now uses
  `primitives/Dialog`. Verified live it gained Escape-to-close for free
  (the hand-rolled version never had that).
- [x] Repeated delete-button/add-button inline styles in Settings — new
  `deleteBtnStyle`/`accentTextBtnStyle()`, now in `views/Settings/
  shared.tsx`.
- [x] Right-rail panel header/empty-state duplication in the agent
  thread — new `PanelHeader`/`PanelEmptyState` (now in `views/
  AgentThread/shared.tsx`), adopted by `FilesPanel`/`CommandLogPanel`.
  `TerminalPanel`'s own header has a genuinely different padding value
  (4px vs 6px vertical) and was left as its own bespoke bar rather than
  forced into the shared component for a difference that wasn't
  actually duplication.
- [x] Three near-identical "form dialog" implementations
  (`AddProviderDialog`/`CustomToolDialog`/`AddCredentialDialog`) — new
  `FormDialog` wrapper (`views/Settings/shared.tsx`) sharing the title/
  Field-stack/error-slot/Cancel-Save-footer chrome. Each dialog still
  owns its own field state, validation, and save logic — only the
  wrapper is shared. `AddProviderDialog`'s preset-chips row (the one
  piece of markup that didn't fit the other two) is passed through a
  `headerExtra` slot rather than forced into the shared shape.
- [x] `WorkspaceSwitcher.tsx`/`NotificationBell.tsx`'s duplicated
  click-outside listener — new `lib/useClickOutside.ts`.
- [x] `Board.tsx`/`List.tsx`'s shared task-fetching/polling/sorting
  boilerplate (including a duplicated `PRIORITY_ORDER` constant) — new
  `lib/useTaskList.ts`. `Board`'s per-stage filter no longer re-sorts,
  since the hook already returns priority-sorted tasks.
- [x] `api.ts`'s three inconsistent error-handling variants (`throw new
  Error(\`HTTP ${status}\`)`, `throw new Error('')` with a blank
  message, and an unguarded `res.json()` that itself threw a confusing
  parse error on a non-JSON failure body) — new `apiFetch<T>()` helper
  used by every exported function. Also surfaced a 4th, worse variant
  along the way: several mutating calls (`setAutonomous`, `sendMessage`,
  `deleteAgent`, `lockVault`, etc.) never checked `res.ok` at all,
  silently "succeeding" on a failed request — now consistent with
  everything else.

---

## Oversized files worth splitting — all four done

- [x] **`src/agent_knots/cockpit/web/server.py`** (was ~1830 lines) —
  split into `cockpit/web/routes/{agents,tasks,workspaces,settings,
  vault,mcp,tools,workflows,review,fs}.py`, each an `APIRouter` built
  by a `create_router(...)` factory taking whatever dependencies its
  domain needs (`session_manager`, `vault`, `auth`). Also extracted
  `decorators.py` (`raises_as`), `models.py` (all Pydantic request
  bodies — several, like `ToggleRequest`, are shared across more than
  one router), `jsonutil.py` (`_extract_json_object`, used by the
  task-draft endpoint and imported directly by tests),
  `gitutil.py` (shared by `review.py`/`fs.py`), and `htmltemplates.py`
  (the `LOGIN_HTML`/`SPA_SHELL_HTML` string constants). `server.py`
  itself is now just the composition root: auth middleware, login, the
  SPA shell/fallback, and `app.include_router(...)` for each domain —
  the SPA fallback route is still registered dead last, same as
  before, so it can't shadow `/api/*` or `/assets/*`.
- [x] **`frontend/src/views/AgentThread.tsx`** (was ~1075 lines) — split
  into `views/AgentThread/{index,EventRow,TerminalPanel,FilesPanel,
  CommandLogPanel,BrowserPanel,types,shared}.tsx`. `types.ts` holds the
  shared `reduceEvent()` reducer (used by both the top-level thread and
  the delegate sub-thread) plus the SSE-side-effect helpers
  (`recordFileTouch`/`recordCommand`); `shared.tsx` holds
  `PanelHeader`/`PanelEmptyState`; `EventRow.tsx` includes
  `DelegateSubThread` since it's the only thing that opens one.
  `main.tsx`'s `import AgentThread from './views/AgentThread'` needed
  no change — resolves to the directory's `index.tsx` automatically.
- [x] **`frontend/src/views/Settings.tsx`** (was ~910 lines) — split
  into `views/Settings/{index,UsageCard,AccessibilityCard,
  ProvidersCard,ToolsCard,PoliciesCard,McpServersCard,IntegrationsCard,
  VaultCard,WorkspacesCard,shared}.tsx`, same pattern as the
  `AgentThread` split. `shared.tsx` holds `deleteBtnStyle`/
  `accentTextBtnStyle`/`FormDialog`.
- [x] **`src/agent_knots/cli/main.py`** (was 759 lines) — split into
  `cli/{session,cockpit,vault,project,task,settings}.py`, each owning
  its own Typer sub-app, plus `cli/_format.py` for the one genuinely
  shared helper (`format_ts`, used identically by `vault audit` and
  `task show`'s progress log). `main.py` is now just the root Typer
  `app` plus `app.add_typer(...)` wiring. Entry point
  (`agent_knots.cli.main:app` in `pyproject.toml`) needed no change.

All four were verified with a full backend pytest run and/or a full
Playwright pass against a live isolated instance (see "What actually
shipped" below for exact numbers) before committing — none were treated
as "just moving code" without re-proving the app still works end to end.

---

## Lower priority / polish — all resolved

Everything that was previously filed here is done, in a third pass on
this branch after the first two (findings + fixes, then the four large
file splits):

- [x] `SessionManager.start()` did ~10 distinct jobs inline in one
  function — extracted into named private helpers
  (`_resolve_task_context`, `_build_full_prompt`, `_resolve_working_dir`,
  `_build_tools`, `_build_model_instance`, `_maybe_create_sandbox`,
  `_swap_sandboxed_tools`, `_register_hooks`, `_resolve_runtime_type`),
  leaving `start()` as an orchestrator. The Agent/Session/intervention-
  handler construction block deliberately stays inline —
  `ModeInterventionHandler`'s `lambda: session.mode` relies on Python's
  late-binding closures to read `session` before it's actually assigned
  (Agent must be built first, since `Session`'s constructor takes the
  already-built Agent), and that ordering subtlety wasn't worth risking
  by pulling into a helper.
- [x] `Session._cancelled`/`_interrupt_only` were two independent
  booleans for one tri-state concept (not cancelled / cancelled-and-
  ending / cancelled-but-session-stays-alive) — `_interrupt_only` was
  only ever meaningful when `_cancelled` was also true. Collapsed into
  a single `CancelKind` enum (`NONE`/`INTERRUPT`/`STOP`) on
  `Session._cancel_kind`.
- [x] `task/tools.py`'s two validation mechanisms turned out to be a
  real bug, not just style drift: `validate_task_output()` pre-checks
  title/priority/status format, but was only ever wired into
  `create_task`/`update_task` (title/priority) — no tool actually
  routed `status` through it, even though the function already had a
  tested status branch ready to use. `update_task_status` happened to
  be safe anyway (its `TaskStatus(status)` conversion lived inside its
  own try/except), but `log_progress` built its `ProgressEntry` — and
  so called `TaskStatus(status)` — *before* its try/except, so an
  agent passing a malformed status there raised an **uncaught
  ValueError** instead of the structured `{"error": ...}` every other
  tool returns. Confirmed live before fixing. Both tools now validate
  through `validate_task_output()` first; 3 new regression tests.
- [x] `tools/registry.py` re-read `disabled_tools.yaml` from disk on
  every `list_builtin()` call, and `toggle_builtin()` read it again
  independently — a single `toggle()` on a built-in tool hit disk
  twice. Now read once in `__init__` into `self._disabled_builtins`,
  mirroring the existing `_custom` dict pattern (loaded once, mutated
  in memory, persisted on write). Safe since `ToolRegistry` is
  instantiated fresh per request.
- [x] `ProvidersCard.handleDelete` silently swallowed delete failures
  with a bare `catch {}` — now logs via `console.warn` (the synthetic-
  legacy-row 404 is expected and still non-fatal, but a real failure
  looked identical to it before).
- [x] Missing `GET /api/workspaces/{id}`/`GET /api/mcp/{name}` singular
  routes — added both, plus `McpServerStore.get(name)` (the store had
  no single-item lookup at all before this) and a shared
  `_workspace_to_response()` helper. 4 new tests.
- [x] `task/store.py` vs `project/store.py`'s CRUD boilerplate, and the
  three frontend dedup items — see their entries under "Redundancy"
  above (the store one was evaluated and deliberately left alone; the
  three frontend ones were all extracted).

---

## What actually shipped

23 commits on `cleanup/code-review` (a separate git worktree — `main`
and the live server were never touched):

1. `fix: task update --assign silently unassigning on unrelated edits`
2. `fix: delegate sub-threads keep fragmenting, tool results always
   render green`
3. `chore: delete confirmed-dead code from the review`
4. `refactor: delete SubprocessRuntime, remove it from every runtime
   picker`
5. `refactor: extract shared atomic-YAML read/write helper`
6. `refactor: dedupe HTTP error handling, agent response, tool toggle in
   server.py`
7. `refactor: extract shared timeAgo() helper`
8. `refactor: dedupe repeated button styles, adopt Dialog primitive in
   Workflows`
9. `refactor: extract shared Field/inputStyle primitive`
10. `refactor: extract shared PanelHeader/PanelEmptyState in
    AgentThread.tsx`
11. `docs: mark code review findings complete, document deferred items`
12. `refactor: split cli/main.py into per-domain command modules`
13. `refactor: extract shared FormDialog wrapper in Settings.tsx`
14. `refactor: split server.py into per-domain route modules`
15. `refactor: split AgentThread.tsx into per-concern files`
16. `refactor: split Settings.tsx into one file per section card`
17. `docs: mark all deferred code review items complete`
18. `refactor: unify api.ts error handling, dedupe click-outside/
    task-list hooks`
19. `refactor: extract SessionManager.start() helpers, collapse cancel
    booleans`
20. `fix: log_progress crashes uncaught on an invalid status string`
21. `refactor: cache disabled_tools.yaml read once per ToolRegistry
    instance`
22. `feat: add missing singular GET /api/workspaces/{id}, GET
    /api/mcp/{name}`
23. `docs: mark all "lower priority / polish" items complete`

(Plus the Autonomous-toggle feature and the mode-gating fix, committed
to `main` directly before this branch was created, since that was
already a complete, tested, user-requested feature rather than part of
the cleanup pass itself.)

Every commit: full backend test suite green (389/389 by the end, up
from 335 at the start of the original review), `tsc --noEmit` +
production build clean where frontend was touched, ruff clean, and —
for anything touching rendered UI, live process behavior, or
request/response shape — verified against a real running instance
before committing, not just "tests pass." Six separate full Playwright
regression runs across this branch's lifetime (one per large split,
one after the frontend polish batch, one final consolidated pass) all
landed at the identical 63/75 passing, the same 12 pre-existing
failures every time (all need a real LLM completion to actually run an
agent turn — multi-turn conversation, mode switching live, tool-use
flows — unrelated to any of these changes), which is strong evidence
none of this branch's changes altered any observable behavior outside
what was specifically intended to change.
