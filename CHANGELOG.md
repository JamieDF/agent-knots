# Changelog

All notable changes to agent-knots are documented here.

## [Unreleased]

### Added
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
