# Code Review — 2026-07-23 / 2026-07-24

Full-codebase review after a long stretch of fast, live feature work. Five
parallel reviews covering backend web/TUI, backend session/runtime, backend
data layer + CLI, the two biggest frontend files, and the rest of the
frontend — plus direct verification (reading the actual Strands SDK source)
of the most serious finding. This was a punch list, not a narrative;
checked off as items got fixed on the `cleanup/code-review` branch (a
separate git worktree, so the live server on `main` was never touched
while this was in progress).

**Status as of this pass:** everything except the four large file splits
and the frontend `FormDialog` extraction is done — see the end of this
file for exactly what's left and why those specific items were
deliberately not attempted in this pass. Every fix below was verified
against the real test suite (382 Python tests, up from 335 at the start of
this file's own creation) and, for anything touching rendered UI or live
process behavior, against a real running instance — not just "tests
pass."

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
  fixed, per the recommendation below — see "Oversized files" section,
  this item is now resolved there instead. `session/worker.py` and the
  `SubprocessRuntime` class are gone; `create_runtime()`/
  `set_runtime_type()` silently fall back to in-process for any
  unrecognized runtime value (including a pre-existing `"subprocess"`
  saved before the removal), verified live that a workspace with that
  value still starts a working session instead of crashing. The
  "Subprocess" option was also removed from the workspace runtime
  dropdown — it was a real, selectable, broken UI choice.

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
- [x] `primitives/StatusDot.tsx`/`PriorityLabel.tsx` — deleted (the
  "adopt them into Board/List/TaskDetail/Dashboard instead" option was
  considered and explicitly not taken — see "Not attempted" at the
  bottom).
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

## Redundancy — mostly extracted

**Backend — done:**
- [x] The ~17 (turned out to be ~14 once the multi-exception/mixed-logic
  handlers were correctly excluded) near-identical
  `try/except ValueError -> HTTPException` blocks in `server.py` — new
  `@raises_as(status_code)` route decorator. Verified against a real
  FastAPI app first that `functools.wraps` preserves the signature
  FastAPI needs for parameter injection (`inspect.signature()` follows
  `__wrapped__`) before applying it broadly — a decorator that broke
  that silently would have been a much worse bug than the duplication
  it fixes. The handlers with real multi-step logic (`POST
  /api/sessions`, `PATCH /api/tasks/{id}`'s status branch) were left as
  plain `try/except` — they don't fit the "whole handler is one risky
  call" shape the decorator is for.
- [x] Duplicated agent-serialization dict (`list_agents`/`get_agent`) —
  new `_agent_to_response()` helper, matching every other domain's
  existing `_x_to_response()` pattern.
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
  whatever the other has already persisted. Added a regression test
  specifically for the subtle failure mode this could have introduced
  (title + assign in the same PATCH, both must survive) and verified it
  live with curl against a running server, not just the test suite.
- [x] Cross-file duplicate tool-toggle branching (`server.py` /
  `cockpit/tui/app.py`) — new `ToolRegistry.toggle()`. Along the way,
  fixed a latent TUI-only bug: its copy of the branching didn't check
  built-in membership before assuming a name was one, so toggling a
  genuinely nonexistent tool there silently no-opped instead of
  raising like the web route did — both now share the web route's
  stricter, correct behavior.
- [ ] `task/store.py` vs `project/store.py`'s shared CRUD boilerplate —
  **not attempted.** Still valid, still lower priority than everything
  above per the original note (`TaskStore`'s domain logic on top means
  full unification isn't clearly worth it).

**Frontend — done:**
- [x] `Field`/`inputStyle` duplicated across 6 files — new
  `primitives/Field.tsx`, adopted by all 6. `tsc` was clean with zero
  errors across all six migrated files on the first attempt, which
  would have caught any prop-shape mismatch immediately.
  `FolderPicker.tsx`'s own `inputStyle` deliberately left alone —
  different layout context and font, not just a copy-paste duplicate.
- [x] `timeAgo`/`rel` duplicated 3× — new `lib/format.ts`.
- [x] `Workflows.tsx`'s hand-rolled dialog overlay — now uses
  `primitives/Dialog`. Verified live it gained Escape-to-close for free
  (the hand-rolled version never had that).
- [x] Repeated delete-button/add-button inline styles in `Settings.tsx`
  — new `deleteBtnStyle`/`accentTextBtnStyle()`, under the `// ──
  shared ──` banner comment that was already there but never actually
  shared anything until now.
- [x] Right-rail panel header/empty-state duplication in
  `AgentThread.tsx` — new `PanelHeader`/`PanelEmptyState`, adopted by
  `FilesPanel`/`CommandLogPanel`. `TerminalPanel`'s own header has a
  genuinely different padding value (4px vs 6px vertical) and was left
  as its own bespoke bar rather than forced into the shared component
  for a difference that wasn't actually duplication.
- [ ] Three near-identical "form dialog" implementations
  (`AddProviderDialog`/`CustomToolDialog`/`AddCredentialDialog` in
  `Settings.tsx`) — **not attempted**, see "Not attempted" below.
- [ ] `WorkspaceSwitcher.tsx`/`NotificationBell.tsx`'s duplicated
  click-outside listener, `Board.tsx`/`List.tsx`'s shared boilerplate,
  `api.ts`'s inconsistent error-handling variants — **not attempted**,
  all still valid, all still explicitly lower priority than everything
  above in the original review.

---

## Oversized files worth splitting — analysis stands, none attempted this pass

All four concrete split proposals below are unchanged from the original
review and still believed correct — re-read them before starting any of
this work, don't re-derive the boundaries from scratch. See "Not
attempted" at the bottom for why these specifically were left for a
separate pass.

- **`src/agent_knots/cockpit/web/server.py`** (now ~1830 lines — grew
  slightly during this pass from the `@raises_as`/helper additions, net
  duplication still went down). Split into
  `cockpit/web/routes/{agents,tasks,workspaces,settings,vault,mcp,tools,
  workflows,review,fs}.py`, each an `APIRouter` built by a factory
  function taking `session_manager`/`vault`. Concrete line ranges were
  in the original review pass; re-check them against current line
  numbers before starting, since several routes shifted during this
  cleanup (the `@raises_as` conversions shortened many of them by 2-4
  lines each).
- **`frontend/src/views/AgentThread.tsx`** (now ~1060 lines — grew
  slightly from `reduceEvent`/`PanelHeader` extractions, which added
  net-new shared code even as they removed duplication). Split into
  `views/AgentThread/{index,EventRow,TerminalPanel,FilesPanel,
  CommandLogPanel,BrowserPanel,types}.tsx` as originally proposed.
- **`frontend/src/views/Settings.tsx`** (now ~880 lines — net smaller
  after the Field/button-style extractions). Split into one file per
  section card as originally proposed, plus `settings/shared.tsx`.
- **`src/agent_knots/cli/main.py`** (759 lines, unchanged this pass).
  Split into `cli/{vault,project,task,session,cockpit}.py` as
  originally proposed — already internally organized as six sub-apps
  welded together, this is the most mechanical of the four splits.

---

## Lower priority / polish — unchanged, not attempted this pass

Everything in this section from the original review is still valid and
still genuinely lower priority; none of it was touched in this pass.
Worth a skim before the next cleanup pass rather than repeating here
verbatim — see git history for this file's previous version if needed,
or just re-read the codebase at the cited locations:

- `SessionManager.start()` doing ~10 jobs in one function.
- `Session._cancelled`/`_interrupt_only` as two booleans for one
  tri-state concept.
- `task/tools.py`'s two different validation mechanisms.
- `tools/registry.py` re-reading `disabled_tools.yaml` redundantly.
- `ProvidersCard.handleDelete` silently swallowing delete errors.
- Missing `GET /api/workspaces/{id}`/`GET /api/mcp/{name}` singular
  routes.

---

## Not attempted this pass, and why

Two categories of items were deliberately left for a separate pass
rather than rushed at the tail end of a long unsupervised session:

1. **The `FormDialog` extraction** (three near-identical form dialogs in
   `Settings.tsx`). Unlike the other frontend extractions in this pass
   (which were pure styling/markup, verifiable by `tsc` + a quick
   Playwright smoke test), this one touches per-field `useState` +
   error/saving state management across three different forms with
   different field sets — real behavioral surface, not just styling.
   Lower confidence that a mechanical extraction stays 100%
   behavior-preserving without more careful, individually-tested work
   than the rest of this pass's items needed.

2. **The four file splits** (`server.py`, `AgentThread.tsx`,
   `Settings.tsx`, `cli/main.py`). These are the highest *value* items
   in this whole review — genuinely the biggest maintainability win
   available — but also by far the highest *effort and blast radius*:
   each touches import graphs, route/registration order, and (for the
   two frontend files) component composition across the entire file.
   The concrete plans above are believed correct and ready to execute,
   but "believed correct and ready" for a ~1800-line mechanical
   reorganization deserves fresh attention and step-by-step
   verification of its own, not inheriting whatever attention budget
   was left after everything else in this pass. Recommend doing
   `cli/main.py` first if picking one to start with — it's explicitly
   the most mechanical of the four (already internally organized as six
   sub-apps) and has the clearest test story (CLI commands are easy to
   exercise end-to-end).

Both categories are real, valid, unchanged findings — just correctly
sized as their own dedicated work rather than something to rush through
here.

---

## What actually shipped in this pass

10 commits on `cleanup/code-review` (a separate git worktree — `main`
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

(Plus the Autonomous-toggle feature and the mode-gating fix, committed
to `main` directly before this branch was created, since that was
already a complete, tested, user-requested feature rather than part of
the cleanup pass itself.)

Every commit: full backend test suite green, `tsc --noEmit` clean where
frontend was touched, and — for anything touching rendered UI, live
process behavior, or request/response shape — verified against a real
running instance (curl or Playwright) before committing, not just
"tests pass." Backend test count went from 335 (start of the original
review pass) to 382.
