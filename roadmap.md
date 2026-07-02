# Roadmap

This is a high-level sketch of where agentjam is headed. It's not a
commitment — features get added, dropped, and reordered based on what
users actually need.

## v0.1 — Foundation ✅

Core interfaces, file-backed implementations, CLI, modes.

- [x] `Driver`, `Vault`, `TaskStore`, `ProjectStore`, `ContainerRuntime`, `Mode` interfaces
- [x] File-backed implementations (vault, tasks, projects)
- [x] CLI with `project`, `task`, `vault`, `agent`, `session`, `cockpit` subcommands
- [x] 11 default mode files
- [x] Unit tests across all core packages with `-race`

## v0.2 — Container Integration ✅

- [x] Worktree management per agent session (`--worktree` flag, `internal/vcs/git.go`)
- [x] Network policy enforcement (egress DROP rules via iptables in container netns)
- [x] Podman runtime tested against real rootless podman 5.8.2
- [x] Session lifecycle: start (foreground + `--detach`), stop, list, show
- [x] Live event streaming via UNIX socket protocol
- [ ] Container runtime full lifecycle (clone → deps → baseline tests → agent loop → final tests → PR)
- [ ] Per-container resource caps (CPU, RAM, disk quotas)

## v0.3 — TUI Cockpit ✅

- [x] Bubble Tea-based TUI cockpit
- [x] Multi-agent list with live status
- [x] Per-agent focus view (event stream)
- [x] Quick-switch keybindings (j/k, Enter, Esc)
- [x] Assume / relinquish control flows (a/r keys)
- [ ] Task and vault management within the TUI

## v0.4 — Web Cockpit ✅ (basic)

- [x] Web GUI binds to `127.0.0.1:<random-port>`, prints URL at startup
- [x] Token-based auth (generated on first start, cookie-based after login)
- [x] Real-time event streaming via SSE
- [x] Agent list with auto-refresh polling
- [x] Control actions (assume, relinquish, send message)
- [x] Fully self-contained (no CDN dependencies)
- [ ] Diffs and code rendered with syntax highlighting
- [ ] Mobile-friendly responsive layout
- [ ] Multiple agents visible side-by-side
- [ ] **v0.4.1** — `--bind 0.0.0.0` opt-in for LAN access + tunnel support
- [ ] UI redesign based on mockups (status dots, color-coded events, card grid)

## v0.5 — Real Agent Integration (next priority)

- [ ] **OpenCode driver tested against live `opencode serve`**
- [ ] Fix SDK shape mismatches, get real agent running in a session
- [ ] Token/cost tracking from real LLM calls
- [ ] Per-session cost cap (configurable, auto-pause on budget hit)
- [ ] Context trimming: auto-summarize when approaching token limits
- [ ] Graceful shutdown (signal handlers for cockpit + session subprocess)
- [ ] Pause/Resume with correct semantics (non-destructive)

## v0.6 — Multi-agent Orchestration

- [ ] Cross-agent shared scratchpad
- [ ] Conflict detection when two agents edit the same file
- [ ] Result aggregation across multiple agents
- [ ] Broadcast: send a message to multiple agents at once
- [ ] Priority / scheduling (mark which agent gets more compute)

## v0.7 — Observability

- [ ] Session replay (scrub through past events)
- [ ] Time-spent and tokens-per-step analytics
- [ ] Cost tracking per session / task / day
- [ ] Budget alerts (50/80/100% of budget)
- [ ] Session export (Markdown, JSON)

## v0.8 — Provider Expansion

- [ ] Direct provider integrations beyond OpenCode
- [ ] Fallback chains (primary → secondary on error or rate limit)
- [ ] Custom provider plugins
- [ ] Custom thin agent loop (no external dependency)

## v1.0 — Stability and Polish

- [ ] Stable public API
- [ ] SemVer commitment
- [ ] Performance: large task histories, many concurrent agents
- [ ] Documentation: every interface, command, and mode documented
- [ ] Installer: `curl ... | sh` for macOS / Linux / Windows
- [ ] Update mechanism

## Future (post-1.0, parking lot)

- **Multi-user support.** Per-user vaults, audit logs, RBAC.
- **Cloud sync.** Optional encrypted sync via user's own cloud storage.
- **Cloud-hosted version.** A hosted agentjam for teams.
- **Mobile companion.** Mobile UI for monitoring agents on the go.
- **IDE plugins.** VSCode, JetBrains.
- **WASM agent sandboxes.** Faster, lighter isolation than containers.
- **Firecracker microVMs.** Stronger isolation for untrusted code.
- **Voice input.** Talk to your agents.
- **Visual reasoning graphs.** See the agent's reasoning as a graph.

## How to influence the roadmap

- Open an issue describing the use case.
- Upvote existing issues you care about.
- Send a PR that aligns with a roadmap item.
- Propose new items via the decision record process.
