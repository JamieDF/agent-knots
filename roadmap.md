# Roadmap

## Done

- [x] Python rebuild — Replaced Go codebase with Python + Strands Agents SDK
- [x] Vault — AES-256-GCM encrypted credential store with injection templates
- [x] Sessions — Start/stop agents from GUI, TUI, CLI. Multi-turn chat with context
- [x] Web cockpit — Vite + React SPA: overview, board, task detail, settings
- [x] TUI cockpit — Textual: agent list, focus view, tools manager, keyboard shortcuts
- [x] Task system — YAML-backed with progress logs, steps, acceptance criteria
- [x] Kanban board — 6-column board with status chips, priority indicators, inline editing
- [x] Agent tools — 12 built-in (editor, shell, calculator, think + 8 task tools)
- [x] Custom tools — User-defined shell command tools, enable/disable per tool
- [x] Workspaces — Multi-project grouping with task/agent filtering, path isolation
- [x] Runtime modes — In-process (fast) + subprocess (isolated). Configurable per workspace/session
- [x] Model providers — MiniMax, OpenAI, Anthropic, Ollama, custom. Selectable in settings
- [x] Assume/Relinquish — Mode switching with live UI pill updates
- [x] Full task workflow — Draft → Open → In Progress → Agent works → Done. Auto status transitions
- [x] Agent-task integration — Agents create, read, update, log progress on tasks via tools
- [x] Settings page — Model config, tool management, workspace management in one place
- [x] Install script — `./install.sh`: installs uv, syncs deps, builds frontend, installs the `agent-knots` command globally
- [x] Playwright e2e tests — 43 browser tests covering full UI flows
- [x] Python unit tests — 176 tests across vault, session, task, web, sandbox, auth

## Next

- [ ] Container runtime — Podman/Docker isolation with full filesystem + network sandboxing
- [ ] Git worktree integration — Auto-create worktrees per session on workspace repos
- [ ] Session replay — Record and replay agent sessions with timeline scrubbing
- [ ] Multi-agent orchestration — Run multiple agents on the same task, merge results
- [ ] Vault injection for agents — Agents use vault credentials without seeing raw values
- [ ] Rich diff rendering — Syntax-highlighted diffs in progress timeline
- [ ] Cost tracking — Real token counting and cost estimation per session
- [ ] Provider expansion — More direct LLM provider integrations
- [ ] Mobile-responsive layout — Full mobile support for the web cockpit
- [ ] Zero-clone installer — `curl <url>/install.sh | bash` without a
  manual `git clone` first (the script would self-clone); Windows support
