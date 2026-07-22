# Changelog

All notable changes to agent-knots are documented here.

## [Unreleased]

### Added
- **Kanban drag-and-drop.** Task cards on the Board can now be dragged
  between columns to change status, alongside the existing click-to-
  expand-then-click-a-stage-button flow (kept as-is, not replaced).
- **Nicer workspace switcher.** The topbar's workspace scope picker is
  now a proper dropdown (`WorkspaceSwitcher.tsx`) matching the rest of
  the design, instead of a bare native `<select>`.
- **Create-workspace flow from the Dashboard.** A "No workspaces yet"
  prompt now offers "+ Create workspace" whenever there are none,
  instead of only "+ New session" with no way to actually add a
  workspace from the Dashboard at all. The create/edit dialog (now
  shared between the Dashboard and Settings, `WorkspaceDialog.tsx`)
  drops the id field entirely — the backend slugifies one from the
  name and dedupes collisions (`POST /api/workspaces`'s `id` is now
  optional) — and replaces the free-text repository path with a
  server-assisted folder browser (`GET /api/fs/browse`, new
  `FolderPicker.tsx`), since a native OS file dialog can't hand back an
  absolute path a local backend process can use. Once a folder is
  chosen, `GET /api/fs/git-info` detects whether it's a git repo with a
  GitHub remote (SSH, `ssh://`, and HTTPS remote URL forms) and shows a
  clickable `github.com/owner/repo` link right in the dialog.
- **Atelier cockpit redesign — Phase 0 (foundations) + Phase 1 (Tasks/
  Board core).** Full frontend rebuild described in
  `design_handoff_atelier_cockpit/`.
  - *Phase 0*: light/dark theme system with persisted toggle, reactive
    URL-synced workspace scope (no more full-page reload to switch
    workspaces), a shared primitives library (Card/Chip/Toggle/
    StatusDot/PriorityLabel/SectionLabel/Dialog/Mono), BrowserRouter
    with a proper SPA-fallback route for deep links (was HashRouter).
    SSE rewritten end to end: the backend now streams structured JSON
    events (`events.py::serialize_event()`) instead of pre-rendered
    HTML fragments, and multiple simultaneous viewers of one agent
    (e.g. two browser tabs) each get their own event queue instead of
    racing for a single shared one. Six new event kinds (`auto_log`,
    `steer`, `delegate`, `checkpoint`, `user`, `ended`).
  - *Phase 1*: Tasks screen with Board/List tabs (stage-driven columns,
    expand-in-place cards, stage filter chips), a unified task create/
    edit dialog (chip tags, criteria/steps row-list editors, review-gate
    select, "✨ Draft with agent"), and a rebuilt Task Detail (lifecycle
    strip, real clickable acceptance criteria, session/tools-used/
    related-tasks side blocks). Task API gained `review_gate`,
    per-criterion toggling, single-agent detail, and an agent-assisted
    task-drafting endpoint.
  - *Phase 2*: Dashboard rebuilt as one workspace cluster per workspace
    (plus an "Unassigned" bucket), each with a blocker hero (question/
    suggested-answer buttons/reply, sourced from the blocked task's own
    progress log), a 2-up grid of active-session cards, an "up next"
    queue with Start, pipeline-stage counts, and a per-workspace
    auto-assign toggle. A real "New session" dialog
    (attach-to-task/prompt/mode/workspace) replaces both the disabled
    Topbar placeholder from Phase 0 and the old ad-hoc inline
    task-picker. `Project` gained config-only `auto_assign`/
    `max_concurrent` fields (no scheduler enforces them yet).
  - *Phase 3*: Agent Thread fully rebuilt — three-zone layout with a
    collapsible goal rail (⌘B), a renderer for every event kind
    (message, collapsible thinking, merged tool call+result, auto-log,
    steering nudge, delegation cards that expand via their own nested
    SSE subscription to the sub-session, checkpoint+revert, blocker
    ask, user reply, session end), driving/watching-locked/ended
    composer states, a replay scrubber, and Terminal/Files/Preview
    right-rail tabs. New checkpoint/revert endpoints (broadcast-only,
    matching the design prototype's own no-op mock behavior). Verified
    against a real MiniMax M2.7 call, not just a fake test key.
  - *Phase 4*: Workflows screen (board-stage toggles, a Planner/Builder/
    Reviewer role registry with a model/trigger/prompt/tools config
    dialog, a generated workflow diagram, pipeline-template shortcuts)
    and a Review screen (pending diffs derived live from each
    workspace's git status, expand-to-view-diff, approve/reject/
    approve-all). New `workflows/` backend module (`Stage`/`Role`/
    `Trigger` models, YAML-backed `StagesStore`/`RolesStore`) and
    `_maybe_fire_role_triggers()`, which starts an enabled role's agent
    session when a task's status crosses a configured stage boundary
    (`leaves_draft`/`is_started`/`enters_review`) via the task-update
    API — not yet wired to agent-tool-driven status changes, and every
    role ships disabled by default since firing one spends real API
    money. Review approve/reject is git-backed (`git add`+`git commit`
    per file or whole workspace); reject deliberately never discards —
    it only acknowledges, matching the project's stance of never
    automating destructive git operations.
  - *Phase 5*: Vault screen (locked/unlocked card states, credential
    list + add + delete, injection-template chips, audit log — new web
    routes over the existing, unmodified `VaultStore`; credential
    values never appear in a list/get response) and a rebuilt Settings
    screen (Usage card backed by a new append-only JSONL usage ledger,
    named Model-provider profiles with "Set default", consolidated
    Tools, Policies, MCP server registry, Integrations, and Workspaces
    CRUD). New `usage.py`, `policies/` (`PolicyStore`), `mcp_servers.py`
    (`McpServerStore`) backend modules; `Settings` gained `providers`,
    `default_provider`, and `integrations`, additively — `agent.*`
    still holds the one config `resolve_provider()` actually reads, and
    "Set default" just copies a saved profile into it, so the Phase 3
    env-var-precedence fix stays untouched. The daily spend-cap policy
    is the only one with real enforcement — `POST /api/sessions` checks
    today's ledger total and blocks with a 400 once the configured cap
    is reached; the other three policies (migrations guard, pause-
    after-test-failures, no-sudo) are configurable but not yet enforced,
    same as MCP servers (registry only, no client) and Integrations
    (GitHub PR-on-review / phone-push toggles, both config-only — no
    OAuth flow or push infra exists).
  - *Phase 6*: Setup wizard restyled to the real design (logo tile,
    preset chips, plain-YAML warning, Skip / Finish setup →) — it was
    already auto-shown whenever `/api/settings` reports unconfigured,
    since Phase 0/2; this phase just gave it the real look and fixed a
    stale-default prefill bug (see Fixed). Login page (still
    server-rendered, deliberately, per the Phase 0 decision that it
    must work before any JS bundle exists) restyled to the real Atelier
    tokens in both themes, reading the same `agent-knots-theme`
    localStorage key the rest of the app uses via one small inline
    script. A real notification bell replacing the static placeholder —
    badge count is pending blockers specifically, dropdown covers
    blocker + recently-done tasks with deep links, footer toggle wired
    to the real `phone_push` setting from Phase 5. Derived by polling
    the same tasks list the Dashboard already polls rather than a live
    SSE subscription across every active session — a disclosed,
    deliberate scope call, not an oversight.

### Fixed
- **A task created while scoped to a workspace wasn't saved to it.**
  `TaskDialog`'s create path never read the current workspace scope at
  all, so every new task's `project` came back empty regardless of
  which workspace the Tasks screen was scoped to when you clicked "+
  New task" — it just silently landed unassigned. Fixed by reading
  `useWorkspaceScope()` and passing it through as `project` on create.
- **Workspace scope was silently dropped on every in-app navigation.**
  `WorkspaceProvider` derived the current scope live from the `?ws=`
  URL param, but a plain `<Link>`/`<NavLink>` to another route carries
  no query string at all, and the provider only mounts once for the
  whole app — so there was nothing left to re-seed the scope from after
  the first load. Picking a workspace then clicking any nav link reset
  it back to "All workspaces" immediately. Fixed by keeping the scope
  as its own React state (initialized from the URL or localStorage,
  whichever's set), with the URL kept in sync on top of it rather than
  being the source of truth.
- **A session started via a bare "Start" button on a task never
  actually began running.** `SessionManager.start()` only kicks off the
  agent's first turn when `task_description` (the literal prompt text)
  is non-empty — every "Start" action across the Dashboard, Task
  Detail, and Board starts a session with an empty prompt on purpose
  (the task's full context is already baked into the system prompt
  instead). The agent mode session just sat idle, looking dead, until
  something else happened to trigger a turn (e.g. assuming control and
  typing a message). Fixed by falling back to a generic kickoff message
  when a task is attached but no explicit prompt was given.
- **Tasks could skip straight from in_progress to done, bypassing
  review entirely.** `_validate_transition()` only checked acceptance
  criteria for the done gate — a task with none at all (or all of them
  met) could go straight to done from any status. Now a task with
  `review_gate` other than `none` must already be in `review` status
  before it can be marked done; `PATCH /api/tasks/{id}` also now wraps
  this in a clean 400 instead of letting the store's `ValueError`
  propagate as a bare 500.
- **New tasks started in Open, not Draft.** Per the intended workflow
  (draft → open → in_progress → review → done), a task should sit in
  Draft until someone deliberately takes it out. Fixed by changing both
  the `Task` dataclass default and `CreateTaskRequest`'s default to
  `draft`; the CLI, agent-callable `create_task` tool, and web API all
  picked this up automatically since none of them passed an explicit
  status. Also fixed a role-trigger bug this exposed: a task can now
  jump straight from draft to in_progress in one hop (skipping Open),
  which used to fire only the `leaves_draft` trigger or only the
  `is_started` one (an if/elif chain) instead of both.
- **The Tasks screen header's "+ New task" dialog didn't refresh the
  board/list.** It closed the dialog but never told whichever view was
  showing to reload, so a new task only appeared after the next 5s poll
  tick or a manual page refresh. Fixed with a reload-signal prop passed
  down from the shared `Tasks.tsx` shell.
- **"✨ Draft with agent" could fail against MiniMax and other
  OpenAI-*compatible* (not literally OpenAI) providers.** It passed
  `response_format={"type": "json_object"}`, an OpenAI-specific
  strict-JSON-mode parameter not every compatible provider implements —
  an unsupported param 400s the whole completion instead of just
  degrading gracefully. Fixed by dropping it and parsing the completion
  text leniently instead (tolerates markdown code fences and stray
  commentary around the JSON). That lenient parse then surfaced a
  second bug: MiniMax M2.7 is a reasoning model that inlines its
  `<think>...</think>` block directly into a plain completion's
  `message.content` (there's no separate reasoning field to skip), and
  since a coding-task "think" block routinely contains its own literal
  `{`/`}` characters, a naive "first `{` to last `}`" scan could grab
  braces from *inside* the reasoning instead of the real JSON object —
  producing text that wasn't valid JSON at all and surfacing a raw,
  uninformative `json.JSONDecodeError` ("Expecting value: line 1 column
  1 (char 0)") instead of a clear error. Fixed by stripping any
  `<think>` block before parsing, and by making the fallback brace-scan
  itself exception-safe with an actionable error message instead of
  letting a decode error bubble up raw.
- **The Agent Thread's page itself could scroll instead of just its
  event stream.** `#root`/`body` used `min-height: 100vh`, which lets
  them grow past the viewport on a tall page instead of clipping at it
  — so `.canvas`'s `flex: 1; overflow: hidden` had nothing determinate
  to clip against, and the whole page scrolled. Fixed with a fixed
  `height: 100%` (and `overflow: hidden` on body) so the header, goal
  rail, and composer stay fixed in place and only the event stream
  itself scrolls, matching every other screen's `DeskLayout` scroll
  behavior.
- **`PATCH /api/tasks/{id}` silently dropped description/tags/
  acceptance_criteria/steps edits.** `UpdateTaskRequest` was missing
  those fields entirely; the frontend's edit dialog sent them but
  nothing on the backend ever applied them. Fixed with existing-entry
  matching so criteria_met/step status survive an edit that doesn't
  touch them.
- **Task API responses omitted `criteria_met` entirely.** Only
  `acceptance_criteria` (the full list) was ever returned, so the
  frontend had no way to know which criteria were already met on page
  load — every criterion looked unmet until toggled again this session.
- **Dashboard only showed sessions with `running===true` at that exact
  instant**, hiding idle-between-turns or assistant-mode-waiting
  sessions entirely — found via Playwright, not just a cosmetic gap
  (there was no way to click back into an idle session from the
  Dashboard at all).
- **`POST /api/sessions` ignored env-var configuration for the actual
  session**, only for the pre-flight "configured" check. It passed
  `settings.load()`'s file values straight through as override args,
  which always outranks env vars in `resolve_provider()`'s precedence —
  a user configured entirely via `AGENT_KNOTS_*` env vars (the
  documented zero-touch install path) would see `configured: true` in
  the UI but every session would silently build against the wrong
  model. Found by testing against a real MiniMax M2.7 key.
- **`<think>...</think>` reasoning tags commonly split across multiple
  stream deltas were misclassified.** The per-fragment heuristic had no
  memory of an already-open think block, so most of a multi-fragment
  thinking block leaked through as plain assistant-message text, tag
  literals included. Now stateful across chunks, with tags stripped.
- **Streamed tool-call args re-emit the same event as they accumulate**
  (empty → partial → complete) — rendered as 2-3 duplicate tool cards
  until the frontend started updating the existing card by id instead
  of appending a new one per update.
- **Assume/Relinquish looked unresponsive** for up to one 3s poll cycle
  (mode chip/composer only updated on the next background poll) — now
  applies optimistically on click.
- **The `openai/`-prefixed model-id convention doesn't work.**
  `OpenAIModel` sends `model_id` as-is with no prefix-stripping, and
  `litellm` (which would understand `provider/model` routing) is a
  listed dependency never actually imported anywhere. Fixed the
  MiniMax-specific docs (`provider.py`, `docs/quickstart.md`), which
  were fully confirmed broken against a real call; the same issue likely
  affects the default OpenAI preset and 2 of the other 3 Setup Wizard
  presets but needs its own dedicated look rather than a rushed fix here.
- **`StagesStore`/`RolesStore` returned shared mutable defaults.**
  `list()` did a shallow `list(DEFAULT_STAGES)`/`list(DEFAULT_ROLES)`,
  which copies the list but not its `Stage`/`Role` elements — `update()`/
  `toggle()` mutating a returned object corrupted the shared
  module-level defaults for the rest of the process. Caught by a real
  pytest cross-test contamination failure. Fixed with `copy.deepcopy()`.
- **`POST /api/review/approve` didn't check `git add`/`git commit`'s
  exit code.** A failing commit still returned `{"status":
  "committed"}` to the client. Caught by a Playwright test expecting a
  second commit that never landed. Now raises a 500 with the captured
  stderr if either command fails.
- **A test for the new "Set default" provider action left `agent.api_key`
  set to a fake test key with no way to undo it**, since `DELETE
  /api/settings/providers/{name}` only removes the saved profile, not
  an already-applied default, and `PUT /api/settings` deliberately
  treats an empty `api_key` as "leave unchanged" (so a blank PUT can't
  accidentally wipe a real key). Fixed in the test by reading and
  restoring the raw `settings.yaml` directly, rather than adding a new
  API-level way to blank a key that isn't needed anywhere else yet.
- **The Setup Wizard could show the MiniMax preset chip selected while
  the Model ID field silently held a stale `openai/gpt-4o-mini`.**
  `AgentSettings.default_model` has a non-empty dataclass default even
  on a totally fresh install, and the wizard's prefill effect trusted
  it unconditionally. Fixed by only prefilling from existing settings
  when `base_url` or `api_key` is actually non-empty — both correctly
  default to `""`, unlike `default_model`.

- **`install.sh`.** One script, run after `git clone`: installs `uv` if
  missing, `uv sync`s Python dependencies, builds the web cockpit
  frontend (skipped with a clear warning if Node isn't available), and
  installs the `agent-knots` command globally via `uv tool install`.
  Idempotent — safe to re-run.
- **Acceptance-criteria enforcement.** `Task.criteria_met` tracks which
  acceptance criteria have been explicitly marked satisfied via the new
  `mark_criterion_met` task tool/CLI. `TaskStore` now refuses a transition
  to `done` (via `set_status` or a status-carrying `log_progress` call)
  until every criterion is marked met. Previously nothing enforced this —
  an agent could mark a task done with unmet criteria and nothing stopped
  it.
- **Real resource limits on shell/custom-tool execution.**
  `sandbox_tools.run_confined()` applies CPU/memory limits and kills the
  whole process group (not just the direct child) on timeout, fixing
  orphaned background processes that the old `subprocess.run(timeout=...)`
  could leave behind. This is not a full security sandbox — see
  `sandbox_tools.py`'s module docstring for what it does and doesn't
  cover.
- Tests for `SessionManager.start()` and `session/runtime.py`, both
  previously at zero coverage (31 new tests total this session).
- **CLI: `project` subcommand group.** `create`, `list`, `show`, `update`,
  `delete` now wired to the existing `ProjectStore` (previously only
  `project list` existed, and only as a stub — the web cockpit already
  had full CRUD via `/api/workspaces`).
- **CLI: `vault template` subcommand group.** `add`, `list`, `show`,
  `remove` for managing per-credential injection templates (`--env`,
  `--file`, `--stdin`, `--wrapper`), matching the `VaultStore` methods
  that already backed the data model. Actually *using* a template to
  inject a credential into a spawned command (an agent-callable
  `vault_use` tool) is still not implemented — see roadmap.

### Fixed
- **`delegate_task` (multi-agent delegation) now actually reaches the
  agent.** It was being appended to the tool list *after* the Strands
  `Agent` was already constructed with the earlier list, so the tool
  almost certainly never registered.
- **`InProcessRuntime` was dead code.** `SessionManager.start()` never
  constructed it and ran the agent loop directly instead, bypassing the
  `SessionRuntime` abstraction. It's now wired through `create_runtime()`
  like the subprocess path. Fixing this also surfaced and fixed a related
  bug: `create_runtime()` ignored an explicitly resolved runtime type
  (e.g. a per-project override) in favor of a possibly-stale global
  setting.
- **Disabling a built-in tool actually disables it now.**
  `ToolRegistry.list_builtin()`/`list_enabled()` hardcoded every built-in
  as enabled and never read the disabled-tools file — toggling one off
  (from the web Settings page or TUI) persisted the change but had zero
  effect on which tools an agent actually got.
- **Custom tools now run in the session's workspace, not the server's own
  cwd.** They previously ran via `subprocess.run()` with no `cwd` set at
  all, silently ignoring whatever workspace was configured.
- **Auth token comparisons are constant-time again.** `server.py`'s
  middleware and `/login` were comparing tokens with plain `==`/`!=`
  instead of `auth.py`'s `verify_token()` (which exists specifically to
  avoid timing attacks) — the helper was there, just unused. Consolidated
  onto one implementation and added `Authorization: Bearer` support to
  the actual middleware (previously only the dead `Auth.require()` had
  it). Also fixed `Auth.cockpit_url`, which was a `@property` that
  couldn't accept the `host`/`port` arguments it declared.
- **`WorkspaceSandbox.max_output`/`max_file_size` are enforced now.**
  Shell output is truncated past `max_output`; editor writes past
  `max_file_size` are rejected before touching disk. Both fields existed
  but were never read by anything. `allowed_urls` was removed instead of
  enforced — no tool exists for it to gate, and the shell tool's
  unrestricted network access would have made a URL allowlist on some
  future tool meaningless anyway.
- **The GUI setup wizard now honors `AGENT_KNOTS_*` env vars, not just
  the settings file.** `GET/PUT /api/settings`'s `configured` flag and
  `POST /api/sessions`'s pre-flight check both used to call
  `settings.is_configured()`, which only looks at
  `~/.agent-knots/settings.yaml`. A user configured entirely via env vars
  (common for containers/CI) would see the wizard every time and
  literally could not start a session from the web GUI — the 400 fired
  before `SessionManager.start()` ever got a chance to resolve the env
  vars itself. Both now use `provider.resolve_provider().is_configured`,
  matching the CLI's actual precedence (flags → env vars → file).
- **The setup wizard no longer claims your API key is "stored
  encrypted."** It's plain-text YAML in `settings.yaml` — only the vault
  encrypts anything. Fixed the copy to say so and point at the vault for
  actual encrypted storage.

### Removed
- **`save_checkpoint`/`load_checkpoint`.** Implemented but never called
  from anywhere (no CLI command, no API route). `inject_memory` already
  covers cross-session continuity via the task's progress log; real
  session/agent-state resume would need to serialize actual conversation
  history, which is a real feature to design later, not something worth
  half-wiring up as-is. See `docs/strands-features.md`.
- **`Auth.require()`.** Assumed a per-route `Depends()` architecture the
  app doesn't use, so it was a second, unreachable auth implementation
  rather than a real option — see the auth fix above.

Tests: 106 → 171 this session (65 new), including first-ever coverage for
`sandbox_tools.py`, `session/runtime.py`, `SessionManager.start()`, task
tool validation, and authenticated web requests — all previously at zero.

### Changed
- **Renamed project from "AgentJam" to "agent-knots".** Python package is
  now `agent_knots` (import path), CLI binary is `agent-knots`. Default
  data directory is now `~/.agent-knots/`. Legacy Go implementation
  (`cmd/`, `internal/`, `go.mod`) removed — superseded by the Python
  rebuild below.

## [Unreleased] — Python Rebuild (2026-07)

### Added
- **Python rebuild** — Complete rewrite from Go to Python on Strands Agents SDK
- **Web cockpit** — Vite + React SPA with agent cards, Kanban board, task detail, settings
- **TUI cockpit** — Textual TUI with agent list, focus view, tools manager, keyboard shortcuts
- **Task system** — YAML-backed tasks with progress logs, steps, acceptance criteria
- **Kanban board** — 6-column board with status chips, priority indicators
- **Vault** — AES-256-GCM encrypted credential store (ported from Go)
- **Agent tools** — 11 built-in: editor, shell, calculator, think + 7 task tools
- **Custom tools** — User-defined shell command tools via settings
- **Workspaces** — Multi-project grouping with task/agent filtering, path isolation
- **Runtime modes** — In-process (fast) + subprocess (isolated), per workspace/session
- **Assume/Relinquish** — Mode switching with tool gating via Strands Interventions
- **Multi-turn chat** — Sequential conversation with context retention
- **Agent panels** — Terminal, Review, Code, Browser tabs in focus view
- **Memory** — Cross-session progress injection into system prompt
- **Multi-agent** — `delegate_task` tool for spawning sub-agents
- **Checkpoint** — Session state save/load for pause/resume
- **Steering** — Tool outputs validated against task acceptance criteria
- **Structured output** — Task data validation (title, status, priority)
- **Real token tracking** — Model call hooks report actual token usage + cost
- **Auto progress logging** — Tool calls auto-log to task progress

### Tests
- 106 Python unit tests (vault, session, task, web)
- 43 Playwright e2e tests (cockpit flow, task CRUD, board, settings, panels, runtime)

- **Per-session subprocess management.** `session start --detach` forks a
  child process (`agentjam session run <id>`) that holds the driver alive,
  serves events on a UNIX socket, and writes PID/sock/log files.
- **Live event streaming protocol.** Each session exposes a UNIX socket
  (`~/.agentjam/sessions/<id>.sock`) that broadcasts JSON-encoded events
  to any connected client. `session logs <id>` follows the stream.
- **Bidirectional control channel.** The same socket accepts control
  messages (set-mode, send) from clients, enabling assume/relinquish and
  message injection from any UI surface.
- **Session discovery.** `live.List()` scans the sessions directory for
  live PID files, verifies process liveness, and cleans up stale entries.

### Added — Drivers

- **Mock driver** (`internal/agent/driver/mock`). 364 LOC. Emits scripted
  agent events (thinking, tool calls, messages, mode changes) on a timer.
  Supports SetMode/Send for testing take-over flow. Used by all demos
  and integration tests.

### Added — Take-over Flow

- **Assume/relinquish control.** Mode swap between `agent` and `assistant`.
  Implemented across three surfaces:
  - CLI: `session assume <id>`, `session relinquish <id>`, `session send <id> <msg>`
  - TUI: `a` key (assume), `r` key (relinquish)
  - Web: POST endpoints + action buttons
- The control channel delivers mode-swap commands to the session
  subprocess, which calls `driver.SetMode()` and emits a state-change event.

### Added — Git Worktree Integration

- **`--worktree` flag** on `session start`. Creates a real git worktree
  at `.agentjam/worktrees/<session-id>/` with a branch named
  `agent-<session-id>`. Worktree is removed and branch deleted on stop.
- `internal/vcs/git.go` (192 LOC): CreateWorktree, RemoveWorktree,
  DeleteBranch, Cleanup, IsGitRepo — all via `git` shell-outs.

### Added — Egress Filtering

- **iptables DROP rules** in the container's network namespace for 12
  CIDR ranges (RFC1918, link-local, loopback, cloud metadata endpoints).
  Installed via `podman unshare nsenter -t <PID> -n iptables -A OUTPUT`.
- `internal/container/egress.go` (109 LOC): InstallEgressRules,
  VerifyEgressRules. Non-fatal on failure (logged, not fatal).
- 4 egress unit tests + integration verification.

### Added — TUI Cockpit (v0.3)

- **Bubble Tea TUI** with two views: agent list and per-agent focus.
  - Agent list: live status, mode, uptime, tokens, current action.
    j/k to navigate, Enter to focus.
  - Focus view: real-time event stream from the session's event socket.
    a/r to assume/relinquish, p to pause, Esc to go back.
- `liveRegistry` caches `liveDriver` instances by session ID to avoid
  duplicate socket connections on every poll tick.
- `streaming` flag prevents goroutine accumulation from re-issuing
  `watchEvents` on every 2-second tick.

### Added — Web Cockpit (v0.4)

- **Browser-accessible cockpit** at `127.0.0.1:<random-port>`.
  - Token auth: 64-hex-char token generated on first start, saved to
    `~/.agentjam/cockpit.token` (mode 0600). Cookie-based after first
    login. `?token=` query param for one-click CLI integration.
  - Agent list page: vanilla JS `fetch()` polling every 2 seconds.
    Agent cards with status, mode, uptime, tokens, cost.
  - Agent detail page: SSE event stream via `EventSource`. Each browser
    tab gets its own event socket connection (no sharing issues).
  - Control actions: Assume, Relinquish, Send message (POST endpoints).
  - Fully self-contained: inline CSS, no CDN dependencies.
- `internal/cockpit/web/` package (671 LOC): server.go, handlers.go,
  sse.go, templates.go.

### Added — Testing

- **Integration test suite** (`internal/integration/`, 651 LOC, 10 tests).
  Build-tagged (`//go:build integration`). Exercises the full lifecycle:
  session start → event streaming → control channel → worktree → stop.
  Run with: `go test -tags integration ./internal/integration/...`
- **Smoke test script** (`scripts/smoke.sh`, 13 checks). Bash end-to-end
  covering lifecycle, events, takeover, worktree. All passing.

### Added — Podman Fixes

- Rootless podman 5.8.2 verified working. Network mode `"private"` → `""`
  (pasta creates isolated netns). `--storage-opt` disabled by default
  (only works on XFS+overlay). `--userns keep-id` confirmed working.

### Fixed

- **Duplicate events in cockpit TUI.** Registry created new `liveDriver`
  (new socket connection) on every 2-second tick. Event server broadcasts
  to all connected clients → fan-out amplification. Fixed by caching
  `liveDriver` instances by session ID + tracking streaming state.
- **CDN dependencies in web cockpit.** HTMX and Pico CSS loaded from CDN
  that was unreachable. Replaced with inline CSS + vanilla JS.
- **Expanded `<details>` collapsing on poll.** Agent list innerHTML swap
  destroyed open state every 2s. Fixed by tracking open IDs and restoring.
- **P0/P1 code review fixes.** Send/Stop race, uptime bug, sync.Once→mutex,
  path traversal, decode errors, PID file leak.

### Changed

- **Renamed project from "harness" to "AgentJam".** Module path is now
  `github.com/JamieDF/agentjam`. CLI binary is now `agentjam` (single word).
  Default data directory is now `~/.agentjam/`.

## [0.1.0] - 2026-06-30

### Added

- Initial release: core interfaces, file-backed implementations, CLI, modes.
- `driver.Driver`, `vault.Vault`, `task.Store`, `project.Store`,
  `container.Runtime`, `mode.Loader` interfaces.
- Vault (AES-256-GCM, argon2id, injection templates, audit log).
- Task system (progress logs, acceptance criteria, step tracking).
- Project workspaces (multi-repo YAML).
- Podman container runtime (CLI-based).
- OpenCode driver via Go SDK (written, not live-tested).
- 11 default modes as markdown files.
- Unit tests across all core packages with `-race`.
