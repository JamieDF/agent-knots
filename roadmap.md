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
- [x] Model providers — MiniMax, OpenAI, Anthropic, Ollama, custom. Selectable in settings
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
- [x] Playwright e2e tests — ~74 browser tests covering full UI flows
- [x] Python unit tests — 350+ tests across vault, session, task, web, sandbox, auth
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

## Next

- [ ] Container runtime — Podman/Docker isolation with full filesystem + network sandboxing
- [ ] Git worktree integration — Auto-create worktrees per session on workspace repos
- [ ] Multi-agent orchestration — Run multiple agents on the same task, merge results
- [ ] Vault injection for agents — Agents use vault credentials without seeing raw values
- [ ] Syntax-highlighted diffs — Review screen colors added/removed lines
  today but doesn't syntax-highlight by language
- [ ] Per-provider cost accuracy — Token counts are real; cost is still a
  flat estimate ($0.30/1M tokens) regardless of actual provider/model pricing
- [ ] Provider expansion — More direct LLM provider integrations
- [ ] Mobile-responsive layout — Full mobile support for the web cockpit
- [ ] Zero-clone installer — `curl <url>/install.sh | bash` without a
  manual `git clone` first (the script would self-clone); Windows support
