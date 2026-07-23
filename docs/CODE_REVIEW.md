# Code Review — 2026-07-23

Full-codebase review after a long stretch of fast, live feature work. Five
parallel reviews covering backend web/TUI, backend session/runtime, backend
data layer + CLI, the two biggest frontend files, and the rest of the
frontend — plus direct verification (reading the actual Strands SDK source)
of the most serious finding. This is a punch list, not a narrative; check
items off as they're fixed.

---

## 🔴 Real bugs currently shipping (fix these regardless of anything else)

- [ ] **Mode gating (Assume/Relinquish, Reviewer/Security) does nothing.**
  `src/agent_knots/intervention.py` — `ModeInterventionHandler` defines
  `on_before_tool_call`, `on_after_tool_call`, `on_before_model_call`,
  `on_after_model_call`. Strands' actual `InterventionHandler` base class
  (`.venv/.../strands/interventions/handler.py`) uses `before_tool_call`,
  `after_tool_call`, `before_model_call`, `after_model_call` — **no `on_`
  prefix**. Its registry (`strands/interventions/registry.py:58-62`,
  `_is_overridden`) only registers a hook if
  `getattr(type(handler), method) != getattr(InterventionHandler, method)`
  for the exact base-class method name. Since none of the four methods
  match, `_register_hooks` never wires this handler into anything — the
  four `on_*` methods are dead code, never called by the framework.
  **Verified directly** by reading the installed SDK source, not just
  trusting the claim.
  Net effect: tool calls execute in every session mode, including
  `assistant` (user driving) and `reviewer`/`security` (meant to be
  read-only) — the entire point of the take-over flow. The mode pill still
  flips DRIVING/WATCHING correctly in the UI, so it looks like it's
  working. Zero test coverage anywhere (`grep` for `intervention` across
  `tests/` returns nothing).
  **Fix:** rename the four methods to drop the `on_` prefix. Add a
  regression test that actually asserts a tool call is denied while in
  `assistant` mode (not just that the mode field flips).

- [ ] **CLI `task update` silently unassigns a task on every call that
  omits `--assign`.** `src/agent_knots/cli/main.py:707,721-722` —
  `assign` defaults to `typer.Option("", "--assign", ...)`, i.e. `""`,
  never `None`. The guard `if assign is not None:` is therefore always
  true, so `agent-knots task update T-x --title foo` (no `--assign` at
  all) unconditionally calls `store.assign(task_id, "")`, wiping any
  existing assignment as a side effect of an unrelated edit.
  **Fix:** default to `None` (`str | None`), check `if assign is not
  None:`. Trivial, zero risk. No dedicated test file for `cli/main.py`
  exists, which is why this wasn't caught.

- [ ] **`SubprocessRuntime` is fully broken, and worse than the known
  issue.** `src/agent_knots/session/runtime.py` (lines 30, 137, 143, 179)
  and `session/worker.py` still reference `session._events.put(...)` — an
  attribute `Session` no longer has, replaced by
  `_subscribers`/`_history`/`_broadcast()` when the SSE fan-out fix
  landed (see `docs/RETRO.md`). First real event in a subprocess-runtime
  session raises `AttributeError`. Beyond that already-known issue:
  `worker.py`'s own `_chunk_to_event` (`worker.py:184-225`) is a second,
  independently-drifted copy of `manager.py`'s `_chunk_to_event`
  (`manager.py:553-735`) — the in-process version was patched to dedupe
  streamed-vs-final message chunks and to correctly split `<think>` tags
  that straddle a delta boundary; `worker.py`'s copy has neither fix. So
  patching the `_events` crash alone would still leave subprocess-mode
  sessions double-emitting responses and mis-splitting thinking blocks.
  Zero test coverage for `SubprocessRuntime.start/_read_events/send/
  set_mode` (`test_session/test_runtime.py` only exercises
  `InProcessRuntime`).
  **Recommendation:** delete `SubprocessRuntime` + `session/worker.py`
  entirely rather than fix-and-maintain two independently-drifting
  chunk-parsers — nothing currently sets `runtime=subprocess` in practice
  (default is `inprocess`), and the stated focus right now is the web
  cockpit, not runtime isolation.

- [ ] **Delegated sub-agent threads have the same event-fragmenting bug
  already fixed for the main thread.** `frontend/src/views/
  AgentThread.tsx:685-707` (`DelegateSubThread`) subscribes to its own SSE
  stream and just does `[...prev.slice(-100), {...evt, id}]` — none of
  the dedup/merge/accumulate logic the main thread's SSE handler
  (`AgentThread.tsx:86-139`) got in commits 9f49e88/a7261e8 (tool-call
  update-in-place, tool-result-by-adjacency merge, consecutive message/
  thinking delta accumulation into one growing bubble). A sub-agent's
  nested thread will render as dozens of tiny fragment bubbles and
  duplicate tool-call cards — exactly the bug those commits fixed
  elsewhere, unfixed here.
  **Fix:** extract the accumulation/merge logic from the main SSE
  effect into a shared `reduceEvent(prev, evt)` helper, use it in both
  places.

- [ ] **Tool-call results always render green, regardless of success or
  failure.** `frontend/src/views/AgentThread.tsx:588` — `evt.result` is a
  full `SSEEvent` with a structured `tool_result` (`stdout`/`stderr`/
  `exit_code`/`error`), but only `evt.result.message` is read, always
  styled `color: 'var(--ok)'`. A failed shell command (non-zero exit)
  renders identically to a successful one.
  **Fix:** branch on `evt.result.tool_result?.exit_code`/`error` to pick
  an err/ok color.

---

## Dead code (safe, mechanical deletions)

- [ ] `frontend/src/views/ToolManager.tsx` (whole file, ~143 lines) + its
  `/tools` route in `main.tsx:44` — confirmed exact functional duplicate
  of `Settings.tsx`'s `ToolsCard`/`CustomToolDialog`, against the same
  API. No nav link points at `/tools` anywhere. Nothing needs porting
  first; Settings' version is actually the more consistent one (uses
  shared primitives, `ToolManager.tsx` hand-rolls its own overlay).
- [ ] `frontend/src/lib/api.ts:154` — `updateTool()` has zero call sites
  anywhere (checked `.ts`/`.tsx` and `cockpit.spec.ts`).
- [ ] `frontend/src/components/primitives/StatusDot.tsx` and
  `PriorityLabel.tsx` — exported from the barrel, zero import sites.
  `Board.tsx`, `List.tsx`, `TaskDetail.tsx`, `Dashboard.tsx` all still
  hand-roll their own inline status dots/priority spans instead — a
  half-migration. Either delete the two primitives or (better) actually
  switch those four call sites over to them.
- [ ] Dead Python imports: `Depends` (`cockpit/web/server.py:21`),
  `LockState` (`server.py:55`), `PosixShellSandbox`
  (`session/manager.py:25`), `os`/`subprocess`/`Path`
  (`session/runtime.py:12,13,18`), `import sys` (`cli/main.py:11`),
  `import time` (`session/worker.py:33`), `DEFAULT_TOOLS` imported but
  unused in both `manager.py:232` and `worker.py:72`.
- [ ] `settings.py:120-123` — `is_configured()` is a dead duplicate; every
  real check goes through `ProviderConfig.is_configured` in
  `provider.py`.
- [ ] `workflows/store.py:103-104` — `RolesStore.get()` has no call site
  (its siblings `list`/`save`/`update`/`enabled_for_trigger` are all
  used).
- [ ] `tools/registry.py:31-33` — `ToolInfo.id` property never read
  anywhere (server code reads `.name`/`.description` directly).
- [ ] `events.py:20-21` — `EventType.PROGRESS` and `EventType.BLOCKER` are
  never emitted by anything. `BLOCKER` is defensively pattern-matched in
  `cockpit/tui/app.py:59` but that branch can never fire. Delete, or note
  in the enum that they're reserved for a future feature.
- [ ] `session/manager.py:124-126` — `SessionManager.__init__`'s
  `sessions_dir`/`vault` fields are assigned and never read again
  anywhere; `SessionManager` is always constructed with just
  `sessions_dir()`, `vault` is never passed. Either wire them in
  (vault-backed secret injection was presumably the intent) or drop the
  params.
- [ ] Dead SSE "close" handling — `AgentThread.tsx:146-152` and
  `lib/sse.ts`'s `onClose`/`'close'` listener. The backend's
  `/api/agent/{id}/events` never emits a named `close` event; the real
  end-of-session signal is a normal `type: "ended"` event, already
  handled by the generic event-append path. The `onClose` callback
  fabricates a redundant second `ended` event — unreachable in practice,
  likely a leftover from before the "dup finish event" fix (a7261e8).

---

## Redundancy worth extracting

**Backend:**
- ~17 near-identical `try: store.thing() except ValueError as e: raise
  HTTPException(status_code=NNN, detail=str(e))` blocks in `server.py`
  (lines 517, 527, 544, 673, 687, 697, 705, 739, 747, 946, 998, 1055,
  1108, 1134, 1253, 1271, 1286) — one `_http_errors()` context manager or
  `raise_as_http()` helper would remove all of them, mechanically.
- Duplicated agent-serialization dict: `list_agents` (`server.py:283-297`)
  and `get_agent` (`server.py:357-366`) build the identical 8-field
  session dict inline — every other domain already has an
  `_x_to_response()` helper, agents/sessions is the one missing it.
- Atomic YAML write/read boilerplate ("write dict → yaml.dump → tmp file
  → optional chmod(0o600) → rename", plus `yaml.safe_load` wrapped in
  try/except) reimplemented independently in `task/store.py:370-384`,
  `project/store.py:59-98`, `vault/store.py:506-519` (JSON variant),
  `settings.py:102-117`, `tools/registry.py:232-266` (×2), and
  `workflows/store.py:63-101` (×2) — the single biggest source of
  backend duplication found. A small `agent_knots/yamlfile.py` with
  `atomic_write_yaml(path, data)` / `safe_read_yaml(path, default)` would
  cut ~120-150 lines and centralize chmod-0600 hygiene that's currently
  applied inconsistently (task/project stores never chmod; vault/
  settings/tools do).
- `update_task` (`server.py:929-987`) calls `TaskStore.update()`
  separately per changed field — a PATCH touching several fields does
  several redundant full-file disk writes and bumps `updated_at`
  repeatedly instead of once. Mutate the in-memory task across all the
  `if` blocks, call `store.update()` once at the end.
- Cross-file duplicate "try custom tool, else built-in" toggle logic:
  `server.py:1141-1150` and `cockpit/tui/app.py:388-392` re-implement the
  identical branching — belongs on `ToolRegistry` as a `.toggle(name)`
  method.
- `task/store.py` vs `project/store.py` share near-identical CRUD
  boilerplate (create/get/list/update/delete/_path/_save/_load) — a thin
  shared `YamlIdStore[T]` base for just the CRUD skeleton would cut ~50
  lines; `TaskStore`'s substantial domain logic on top (transitions,
  dependencies, criteria) means full unification isn't clearly worth it,
  lower priority than the yamlfile.py extraction above.

**Frontend:**
- `Field` component + `inputStyle` const duplicated byte-for-byte across
  `TaskDialog.tsx`, `NewSessionDialog.tsx`, `WorkspaceDialog.tsx`,
  `SetupWizard.tsx`, `Workflows.tsx`, `Settings.tsx` (the last one even
  under a `// ── shared ───` comment that never got followed through).
  `FolderPicker.tsx` has its own near-identical `inputStyle` too. Add
  `primitives/Field.tsx` + export `inputStyle`, mechanical replace across
  6 files.
- Relative-time formatter (`timeAgo`/`rel`) duplicated 3× with near-
  identical logic: `TaskDetail.tsx:21-27`, `NotificationBell.tsx:7-13`,
  `Settings.tsx:580-587`. `lib/priorityColors.ts`/`statusColors.ts`
  already went through this exact consolidation — this is the one that
  got missed. Extract to `lib/format.ts: timeAgo(ts, opts?)`.
- Three near-identical "form dialog" implementations —
  `AddProviderDialog` (`Settings.tsx:306-361`), `CustomToolDialog`
  (`Settings.tsx:392-439`), `AddCredentialDialog` (`Settings.tsx:751-797`)
  — same per-field `useState` + error + saving + reset + try/catch/finally
  + identical Cancel/Save footer shape every time. Extract a shared
  `FormDialog` wrapper or at least the footer component.
- `Workflows.tsx`'s `RoleConfigDialog` (lines 162-192) hand-rolls its own
  `position: fixed` overlay + backdrop-click instead of using
  `primitives/Dialog.tsx` — whose own doc comment explicitly lists "role
  config" as one of the dialogs it's meant to back. Swap in `<Dialog>`;
  loses nothing (Dialog already handles Escape, which the hand-rolled
  version doesn't).
- Repeated inline styles in `Settings.tsx`: the delete-button style
  `{ color: 'var(--err)', fontSize: 14 }` copy-pasted 6× (lines 297, 384,
  508, 719, 838, 851), the "+ Add X" header-button style 4×+ (lines 281,
  376, 518, 825). `AgentThread.tsx` already extracted an equivalent
  `pillBtn` helper for the same problem — Settings never got the same
  treatment, an inconsistency between the two files.
- Right-rail panel headers/empty-states duplicated verbatim across
  `TerminalPanel`/`FilesPanel`/`CommandLogPanel` in `AgentThread.tsx`
  (lines ~818, ~853, ~894 and ~854, ~895) — a shared `PanelHeader`/
  `PanelEmptyState` component would cover all three (and adapt for
  Browser's icon variant).
- `WorkspaceSwitcher.tsx` and `NotificationBell.tsx` both hand-roll the
  same click-outside-closes-dropdown `useRef` + `mousedown` listener —
  only two occurrences, low urgency, but a `useClickOutside(ref, onOutside)`
  hook would remove both.
- `Board.tsx`/`List.tsx` share `PRIORITY_ORDER`, an identical `load`
  callback shape, and an identical `reloadSignal` effect — genuinely
  different views otherwise; only worth a shared `useTaskList()` hook if
  touched again for other reasons.
- `api.ts`'s ~50 fetch wrappers have 3 inconsistent error-handling
  variants (plain `HTTP ${status}`, empty-string `Error` — a minor latent
  bug since callers get nothing to show — and `err.detail` JSON parsing).
  An `apiFetch<T>(path, opts?)` helper would unify this and fix the
  swallowed-message cases; wide-touching change, lower priority than the
  above.

---

## Oversized files worth splitting

- **`src/agent_knots/cockpit/web/server.py`** (1813 lines, 65 route
  declarations across ~10 separable domains, all as closures inside one
  `create_app()`). Concrete split, by current line ranges:
  `cockpit/web/routes/agents.py` (277-551, 765-828),
  `tasks.py` (830-1057), `workspaces.py` (1154-1255),
  `settings.py` (555-655, 658-660), `vault.py` (709-761),
  `mcp.py` (676-708), `tools.py` (1059-1150), `workflows.py` (1257-1288),
  `review.py` (1289-1346), `fs.py` (1348-1393 + health). `server.py`
  itself would shrink to ~300-400 lines: app factory, auth middleware,
  login, SPA shell/fallback, static mounting, shared serialization
  helpers. Each router built by a small factory function taking
  `session_manager`/`vault` — matches the current closure style, no need
  to introduce FastAPI `Depends`-based DI just for this. Mechanical,
  low-risk if done one domain at a time with a smoke test after each, but
  a genuinely large diff — treat as dedicated work, not a drive-by.

- **`frontend/src/views/AgentThread.tsx`** (1042 lines). Split into:
  `views/AgentThread/index.tsx` (header, goal rail, event list, composer,
  resize handle), `EventRow.tsx` (`EventRow`, `Bubble`,
  `DelegateSubThread`, `truncate`), `TerminalPanel.tsx`,
  `FilesPanel.tsx` (+ `recordFileTouch`), `CommandLogPanel.tsx`
  (+ `recordCommand`), `BrowserPanel.tsx` (+ tab-management helpers),
  `types.ts` (`EventItem`, `Tab`, `FileChange`, `CommandEntry`). Each
  panel is already independently complex (websocket+xterm lifecycle, a
  file-content cache, tab-management state) and talks to the parent only
  through plain props — no shared closures needed, so this is close to
  copy-paste-and-import.

- **`frontend/src/views/Settings.tsx`** (894 lines). Lower-risk than
  AgentThread since the section cards share almost no state — each
  fetches its own data on mount. One file per card
  (`settings/UsageCard.tsx`, `AccessibilityCard.tsx`, `ProvidersCard.tsx`,
  `ToolsCard.tsx`, `PoliciesCard.tsx`, `McpServersCard.tsx`,
  `IntegrationsCard.tsx`, `VaultCard.tsx`, `WorkspacesCard.tsx`), plus
  `settings/shared.tsx` for `Field`/`inputStyle`/`Section`, `Settings.tsx`
  left as the thin orchestrator (SECTIONS array, side nav, scroll-spy).

- **`src/agent_knots/cli/main.py`** (759 lines). Already internally
  organized as six clearly delimited sections (session/cockpit/vault+
  templates/project/task/settings), each with its own `typer.Typer()`
  sub-app and its own module-level singleton getter — i.e. already
  structured like six files welded together with comment banners.
  Splitting into `cli/vault.py`, `cli/project.py`, `cli/task.py`,
  `cli/session.py`, `cli/cockpit.py`, each exporting its `Typer` instance
  for `main.py` to `add_typer()`, is the standard Typer sub-app-per-noun
  layout and would take `main.py` itself down to ~60-80 lines of pure
  registration. Real value, not busywork: the documented CLI/web parity
  gaps (no `--description`/`--criteria`/`--tag` on `task update`, no CLI
  workspace archive) are exactly the kind of change that's easy to get
  right in an isolated ~140-line `task.py` and easy to half-do in a
  759-line file with six unrelated concerns and no dedicated tests — the
  `--assign` bug above is a direct symptom of that.

- `vault/store.py` (535 lines) mixes four distinct jobs (crypto
  orchestration/lock-unlock, credential CRUD, template CRUD, audit log)
  in one class. Splitting `AuditLog` and/or `TemplateStore` out as
  composed classes would bring each file under ~200 lines. Medium risk
  (touches a public API used by both CLI and web) — do only if actively
  working in vault code, not as a standalone cleanup.

---

## Lower priority / polish

- `SessionManager.start()` (`manager.py:136-359`) does ~10 distinct jobs
  in one ~220-line function. Natural extraction points: task-context
  resolution, working-dir resolution, tool assembly, sandboxed-tool
  wiring, runtime-type resolution — each already has an implicit single
  responsibility, so this is mechanical, no behavior change, low risk.
- `Session._cancelled`/`_interrupt_only` are really one tri-state concept
  split across two booleans, always set together, only ever read
  together. Collapsing into one `_cancel_mode: Literal["interrupt",
  "end"] | None` removes a field but isn't urgent — `_background_pids` is
  unrelated and not actually confused with the other two.
- `hooks.py:17` type-hints `session: "Session"` as an unresolvable
  string forward-ref (no import, not even under `TYPE_CHECKING`) —
  harmless at runtime, breaks IDE/type-checker resolution.
- `task/tools.py` has two different validation mechanisms for the same
  intent (`validate_task_output()` pre-validates status/priority in some
  call paths; `update_task_status`/`log_progress` construct
  `TaskStatus(status)` directly with their own try/except elsewhere) —
  not true duplication since the store itself does no field validation,
  but inconsistent if this file is touched again.
- `tools/registry.py`'s `list_all()`/`list_enabled()` each independently
  reload `disabled_tools.yaml` from disk — wasteful, not wrong, only
  worth fixing if this path gets hot.
- `ProvidersCard.handleDelete` (`Settings.tsx:275`) silently swallows all
  delete errors (intentional per its own comment, for a synthetic legacy
  row) — worth a `console.warn` so a genuine server error isn't
  indistinguishable from the expected no-op.
- No `GET /api/workspaces/{id}` or `GET /api/mcp/{name}` singular routes,
  unlike tasks/tools which have both list and get-by-id — inconsistent
  API surface, only worth fixing if the frontend actually needs it.

---

## Suggested order

1. Fix the two real bugs (mode-gating rename, CLI `--assign` default) —
   small, safe, high value.
2. Delete confirmed-dead code (ToolManager.tsx, updateTool, unused
   imports/fields/enum members, dead SSE close handler) — batchable,
   essentially risk-free.
3. Decide on `SubprocessRuntime`: delete, or fix + de-duplicate the
   chunk-parser.
4. Extract the shared helpers (yamlfile.py, HTTP-error helper,
   agent-response helper, Field/inputStyle, timeAgo) — mechanical,
   moderate value.
5. File splits (server.py, AgentThread.tsx, Settings.tsx, cli/main.py) —
   biggest diffs, do one at a time, each independently valuable and each
   independently low-risk if done carefully with tests passing after
   each step.
