# Roadmap

## Done

- [x] Python rebuild — Replaced Go codebase with Python + Strands Agents SDK
- [x] Vault — AES-256-GCM encrypted credential store with injection templates
- [x] Sessions — Start/stop agents from GUI, TUI, CLI. Multi-turn chat with context
- [x] Web cockpit ("Atelier" redesign) — Vite + React SPA: Dashboard, Tasks
  (Board/List tabs), Task Detail, Agent Thread, Review, Workflows, Settings
- [x] TUI cockpit — Textual: agent list, focus view, tools manager, keyboard shortcuts
- [x] Task system — YAML-backed with progress logs, steps, acceptance criteria
- [x] Kanban board — configurable stages (Workflows screen), all task
  statuses covered (blocked/planned surface as card badges rather than
  vanishing), drag-and-drop between columns, priority indicators
- [x] Agent tools — 12 built-in (editor, shell, calculator, think + 8 task tools)
- [x] Custom tools — User-defined shell command tools, enable/disable per tool
- [x] Workspaces — Multi-project grouping with task/agent filtering, path
  isolation, full CRUD plus archive/unarchive from Settings
- [x] Runtime — In-process. (A subprocess-isolated runtime existed but
  never actually worked — deleted rather than fixed, see the full
  codebase review item below. Real process isolation is a
  container-runtime roadmap item instead.)
- [x] Model providers — MiniMax, OpenAI, Anthropic, Ollama, DeepSeek, custom. Selectable in settings
- [x] Autonomous toggle — Single on/off switch replacing Assume/Relinquish:
  on lets the agent self-direct from its task, off interrupts whatever's
  running and pauses it for back-and-forth without blocking tool use
- [x] Full task workflow — Draft → Open → In Progress → Review → Done, with
  a real review-gate enforced on the Done transition (not just displayed)
- [x] Task editing — Title, description, priority, tags, acceptance
  criteria, and steps are all editable after creation
- [x] Criteria completion UI — Humans can mark acceptance criteria met
  from Task Detail (previously agent-tool-only)
- [x] Agent-task integration — Agents create, read, update, log progress on tasks via tools
- [x] Vault UI — Full web management (unlock, credentials, audit log)
  folded into Settings; previously 100% CLI-only
- [x] Settings — Sticky section nav across usage, providers, tools,
  policies, MCP servers, integrations, vault, and workspaces
- [x] SSE fan-out — Structured JSON events broadcast to every subscriber
  of a session; multiple browser tabs no longer race for events
- [x] Agent Thread chat UI — Left/right chat bubbles, markdown rendering
  of agent responses, replay scrubber over the session's event history
- [x] Install script — `./install.sh`: installs uv, syncs deps, builds frontend, installs the `agent-knots` command globally
- [x] Playwright e2e tests — 76 browser tests covering full UI flows (74 passing, 2 skipped; needs a provider configured for the live-agent ones)
- [x] Python unit tests — 611 tests across vault, session, task, web, sandbox, auth, git
- [x] Task dependencies — Tasks can depend on other tasks; blocked from
  starting (in the UI and via a `POST /api/sessions` pre-flight check)
  until every dependency is done
- [x] Review-gate security fix — Agents can no longer self-approve their
  own review-gated work; only a human-driven web PATCH can pass a task
  through review
- [x] Real interactive terminal — PTY-backed shell (xterm.js over a
  websocket) in Agent Thread's right rail, plus a Command Log tab (every
  shell command with a timestamp) and click-to-preview in the Files tab
- [x] Browser tab — Multi-tab in-panel browser (address bar, open/close
  tabs) replacing the old static Preview placeholder; a URL the agent
  mentions in chat opens automatically in a new tab
- [x] Background process execution — `background=true` on the shell tool
  lets an agent start a dev server or watcher without the tool's timeout
  killing it; tracked per-session and cleaned up when the session ends
- [x] Stop vs Delete — Composer's Stop now cancels only the current turn
  (session stays open); a separate header Delete ends the session
- [x] Accessibility settings — App-wide font size and font family
- [x] Resizable Agent Thread layout — Drag to resize the chat/rail split,
  clamped to 5–95% of the available width
- [x] Fixed mode-gating actually doing nothing — a method-naming
  mismatch with the Strands SDK meant reviewer/security modes never
  actually denied a tool call despite the code looking like they should
- [x] Full codebase review + cleanup pass — dead code removed, real bugs
  fixed (CLI `--assign` silently unassigning, delegate sub-threads never
  getting the event-accumulation fix, tool results always rendering as
  success), `SubprocessRuntime` deleted rather than fixed (see below)
- [x] Task-scoped session branches — a task's git branch is reused across
  resumed sessions instead of one-off per session; auto-stop on
  review/done/abandoned; every stop leaves a wastebin tombstone
- [x] Vault injection for agents — a task's required credentials resolve
  into shell env vars for the agent's tool calls; the raw value never
  enters the agent's own context
- [x] Multi-agent basics — an advisory role (e.g. a read-only reviewer)
  can share a task alongside the main agent, and an agent can delegate a
  sub-task to its own sub-agent via `delegate_task` (a separate task and
  session, not shared editing of the same one)
- [x] Workspace-scoped agent tasks — a workspace-attached session's
  system prompt tells it which workspace it's in, and `create_task`,
  `read_task`, and `list_tasks` are all confined to that workspace; an
  agent can't create, read, or discover a task in a different one
  (`project` is closed over, not agent-supplied)
- [x] Session history persistence — a stopped session's full event
  transcript is kept in its wastebin tombstone instead of vanishing;
  reopening it from Task Detail's "Past sessions" list replays the whole
  conversation read-only via the same SSE path a live session uses
- [x] Human-readable session names — "sleepy-panda"-style names, unique
  among currently active sessions, shown everywhere an agent appears
  instead of its raw hex id
- [x] Task-level auto-adoption — a session started with no task adopts
  the first task it creates or logs progress on, moving it to
  in_progress the same as a session started with a task from the outset
  (previously only fired from 'open', missing the common case of a
  freshly created task defaulting to 'draft')
- [x] Duplicate-agent prevention — starting a session on a task that
  already has an active writer is refused with a clear error instead of
  two agents silently fighting over the same branch/working tree
- [x] Live Task Detail — polls every 5s so progress an agent writes
  while the page is open shows up without a manual reload; Dashboard
  cards now show a live summary of the agent's most recent action
  instead of just a static "working…"/"paused" word, and the "paused"
  label no longer contradicts an agent that's actively mid-turn
- [x] Review, rebuilt around tasks — lists tasks actually sitting in
  review (not raw git diffs across every workspace, which had no real
  connection to a task's own review status), with per-file or
  all-at-once approve/reject. A task entering review now pauses its
  session instead of stopping it, so rejecting with a reason resumes
  the exact same conversation instead of losing it; approving commits
  and moves the task to done, and only then does the session actually
  stop
- [x] Wastebin performance — history no longer lives inline in the
  small metadata file listed on every poll from three different
  screens; existing large entries self-migrate on first read after
  upgrading (measured: 4.58s → 0.014s for the same list() call)
- [x] Loading spinner — Task Detail and the Tasks Board/List views show
  one on first load instead of nothing, so "still loading" and
  "genuinely empty" no longer look identical

## Next

- [ ] Container runtime — Podman/Docker isolation with full filesystem +
  network sandboxing. Managed workspaces are the enabling step: agent-knots
  owns the directory, so mounting it into a container is a bind-mount of our
  own path rather than exposing the user's real checkout. The seam already
  exists too — `SessionRuntime`/`InProcessRuntime` in `session/runtime.py`,
  plus `Project.runtime` and its dropdown — so a `ContainerRuntime` slots in
  without new architecture
- [ ] Git worktree integration — Auto-create worktrees per session, hanging
  off the managed clone (or `config.worktrees_dir()`, which exists and is
  still unused). This is what would let several agents work one repo at
  once, and what deletes `SessionManager._repo_writers`. Worth protecting:
  `_resolve_working_dir` is the single choke point deciding a session's cwd,
  and under worktrees that becomes a derived per-session path rather than
  `Project.repository` itself — keep new readers of `repository` out of the
  codebase or that refactor gets much harder
- [ ] Playground workspace — A "create a playground" action in Settings that
  stands up a live tour: a workspace, real content, and a batch of seeded
  tasks to click through. Mostly assembly on top of managed workspaces —
  a managed create plus task seeding through the existing `TaskStore`. Open
  question: tag the seeded tasks so demo content is distinguishable from
  real work and teardown is unambiguous
- [ ] Structured state storage — Replace the pile of per-object YAML with
  SQLite (local-first, no server dependency). The store classes are already
  the seam: `TaskStore`, `ProjectStore`, `VaultStore` and `WastebinStore`
  share one CRUD shape over `yamlfile.py` and nothing outside them touches
  YAML, so it's a swap behind those classes rather than a rewrite of their
  callers. `usage.jsonl` and the wastebin history files are the stragglers.
  Symptom worth quoting when this gets picked up: adding one field to
  `Project` means writing it three times — dataclass, `_save`, `_load`
- [ ] Concurrent multi-writer collaboration — more than one agent actively
  editing the same task/branch at once, with conflict/result merging.
  Today only one writer session per task is active at a time (see
  "Duplicate-agent prevention" above); a second writer on the same repo
  also just skips branching rather than fighting over the checked-out
  working tree (`SessionManager._repo_writers`)
- [ ] Syntax-highlighted diffs — Review screen colors added/removed lines
  today but doesn't syntax-highlight by language
- [ ] Per-provider cost accuracy — Token counts are real; cost is still a
  flat estimate ($0.30/1M tokens) regardless of actual provider/model pricing
- [ ] Provider expansion — More direct LLM provider integrations
- [ ] Mobile-responsive layout — Full mobile support for the web cockpit
- [ ] Zero-clone installer — `curl <url>/install.sh | bash` without a
  manual `git clone` first (the script would self-clone); Windows support
- [ ] CI — GitHub Actions running pytest + ruff on every PR; there's none today
