# AgentJam

> Local-first orchestrator for AI coding agents. You stay in control.

AgentJam runs multiple AI coding agents in parallel, each in its own session.
Watch them work in real time from a browser or terminal. Take over any agent
mid-task, hand control back. No dead-end states.

---

## What works right now

| Capability | Status | Notes |
|---|---|---|
| **Session lifecycle** | ✅ Working | Start (foreground or `--detach`), stop, list, show. Subprocess-based with PID tracking. |
| **Live event streaming** | ✅ Working | Bidirectional UNIX socket per session. Events stream to CLI, TUI, and web simultaneously. |
| **Mock driver** | ✅ Working | Scripted agent events for testing and demos. Emit tool calls, messages, mode changes on a timer. |
| **TUI cockpit** | ✅ Working | Bubble Tea. Multi-agent list + per-agent focus view. j/k navigate, Enter focus, a/r assume/relinquish. |
| **Web cockpit** | ✅ Working | Browser UI at `127.0.0.1:<random-port>`. SSE event streaming, token auth, agent cards, control actions. |
| **Take-over flow** | ✅ Working | `a` to assume (agent → assistant mode), `r` to relinquish. Works in TUI, web, and CLI. |
| **Git worktrees** | ✅ Working | `--worktree` flag creates a real git worktree + branch per session. Cleaned up on stop. |
| **Egress filtering** | ✅ Working | iptables DROP rules for 12 CIDRs (RFC1918, link-local, metadata) via `podman unshare nsenter`. |
| **Podman container runtime** | ✅ Tested | Rootless podman 5.8.2 verified. Network mode, storage-opt, userns all fixed. |
| **OpenCode driver** | 🟡 Written, untested | 327 LOC adapter. Never run against live `opencode serve`. SDK shape may need fixes. |
| **Vault** | ✅ Working | AES-256-GCM, argon2id KDF, injection templates, audit log. 1.7K LOC, most battle-tested package. |
| **Tasks** | ✅ Working | YAML file-backed with progress logs, acceptance criteria gating, step tracking. |
| **Projects** | ✅ Working | Multi-repo workspaces, active-project tracking. |
| **Modes** | ✅ Working | 11 markdown mode files. Loader with caching and reload. |
| **Integration tests** | ✅ Passing | 10 Go integration tests (`-tags integration`). Smoke script (`scripts/smoke.sh`) with 13 checks. |
| **Unit tests** | ✅ Passing | 25 test files, ~5.4K LOC. `-race` clean across 16 packages. |

**Stats:** ~10.9K source LOC, ~5.4K test LOC, 43 source files, 26 packages.

---

## Quickstart

```bash
# Build
go build -o agentjam ./cmd/agentjam

# Start a mock agent (no LLM needed — emits scripted events)
agentjam session start --driver mock --detach

# Launch the web cockpit (opens a browser-accessible URL)
agentjam cockpit --web
# → agentjam cockpit (web): http://127.0.0.1:43219/?token=a1b2c3...

# Or launch the TUI cockpit
agentjam cockpit
# → Bubble Tea TUI: j/k navigate, Enter to focus, a to assume, q to quit

# Stop sessions
agentjam session stop <id>
agentjam session list
```

---

## CLI Reference

```
agentjam
├── session
│   ├── start [--driver mock|opencode] [--detach] [--worktree] [--mode agent|assistant]
│   ├── list                          # shows live status (* = running subprocess)
│   ├── show <id>
│   ├── stop <id>
│   ├── logs <id>                     # follow event stream
│   ├── assume <id>                   # switch to assistant mode (take control)
│   ├── relinquish <id>               # switch back to agent mode
│   └── send <id> <message>           # inject a user message
├── cockpit
│   └── [--web]                       # TUI by default, --web for browser
├── project
│   ├── list, create, switch, show, delete, active
├── task
│   ├── list, new, show, status, assign, log
├── vault
│   ├── init, unlock, lock, list, add, remove, show
│   └── template (list, add, remove), audit
├── agent
│   ├── spawn, list
└── version
```

---

## Architecture

```
┌─ agentjam cockpit ──────────────────────────────┐
│                                                   │
│   Web UI (SSE)        TUI (Bubble Tea)            │
│       ↕                   ↕                       │
│   ┌────────────────────────────────────────────┐ │
│   │         live package (IPC layer)            │ │
│   │  UNIX socket per session:                   │ │
│   │    server → clients: event stream (JSON)    │ │
│   │    client → server: control commands        │ │
│   │      (set-mode, send)                       │ │
│   └────────────────┬───────────────────────────┘ │
│                    │                              │
│   ┌────────────────▼───────────────────────────┐ │
│   │     session subprocess (per --detach)       │ │
│   │  ┌──────────────────────────────────────┐  │ │
│   │  │  Driver (mock | opencode | ...)      │  │ │
│   │  │  Events channel → socket broadcast   │  │ │
│   │  │  Control channel ← socket commands   │  │ │
│   │  └──────────────────────────────────────┘  │ │
│   │  Runtime: local | container (podman)       │ │
│   │  Worktree: git worktree per session         │ │
│   └────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

### Packages

| Package | LOC | Purpose |
|---------|-----|---------|
| `internal/agent/driver` | 261 | `Driver` interface — Start, Stop, Events, Send, SetMode, Snapshot |
| `internal/agent/driver/mock` | 364 | Scripted agent for testing/demos |
| `internal/agent/driver/opencode` | 327 | OpenCode SDK adapter (written, not live-tested) |
| `internal/session` | 1,198 | Session records, 6-phase init, local + container runtimes |
| `internal/session/live` | 265 | IPC: event socket protocol, control channel, session discovery |
| `internal/cockpit/tui` | 487 | Bubble Tea TUI: multi-agent list + focus view + keybindings |
| `internal/cockpit/web` | 671 | HTTP server: SSE streaming, token auth, agent list + detail pages |
| `internal/container` | 624 | Runtime interface, isolation profiles, egress filtering |
| `internal/container/podman` | 446 | Podman CLI wrapper (rootless, tested) |
| `internal/vault` | 1,719 | AES-256-GCM vault, injection templates, audit log, plugins |
| `internal/vcs` | 192 | Git worktree operations (create, remove, branch, cleanup) |
| `internal/task` | 746 | Task system with progress logs, acceptance criteria |
| `internal/project` | 466 | Multi-repo project workspaces |
| `internal/mode` | 225 | Markdown → system prompt loader |
| `internal/config` | 95 | Home dir resolution, path helpers |
| `internal/errs` | 57 | Sentinel errors + wrap helper |
| `internal/integration` | 651 | End-to-end integration tests (build-tagged) |
| `cmd/agentjam` | 2,927 | CLI: Cobra commands, session run loop, cockpit launchers |

---

## Project layout

```
agentjam/
├── cmd/agentjam/          # CLI entry point + all cobra commands
├── internal/
│   ├── agent/driver/      # Driver interface + implementations
│   │   ├── mock/          #   scripted test driver
│   │   └── opencode/      #   OpenCode SDK adapter
│   ├── cockpit/
│   │   ├── tui/           # Bubble Tea TUI
│   │   └── web/           # Web cockpit (HTTP + SSE)
│   ├── config/            # Home dir, paths
│   ├── container/         # Runtime abstraction + podman + egress
│   ├── errs/              # Error types
│   ├── integration/       # End-to-end tests (build-tagged)
│   ├── mode/              # Markdown mode loader
│   ├── project/           # Multi-repo project workspaces
│   ├── session/           # Session lifecycle + IPC
│   │   └── live/          #   event socket protocol
│   ├── task/              # Task system with progress logs
│   ├── vault/             # Credential storage + injection
│   └── vcs/               # Git worktree operations
├── modes/                 # 11 default mode .md files
├── scripts/smoke.sh       # 13-check end-to-end smoke test
├── docs/                  # Architecture, ADRs, retrospective
└── mockups/               # HTML UI mockups for design iteration
```

---

## Development

```bash
# Build
GOFLAGS=-mod=mod go build -o agentjam ./cmd/agentjam

# Unit tests (fast)
GOFLAGS=-mod=mod go test -race -count=1 ./...

# Integration tests (slower, exercises real subprocesses)
GOFLAGS=-mod=mod go test -race -count=1 -tags integration ./internal/integration/...

# Smoke test (end-to-end bash script)
./scripts/smoke.sh

# Run web cockpit for manual testing
agentjam session start --driver mock --detach
agentjam cockpit --web
```

Requires Go 1.25+. Uses `GOFLAGS=-mod=mod` to work around a transient
`muesli/ansi` proxy issue.

---

## Status

**Pre-alpha, foundation-complete, integration-working.**

All interfaces are stable. Session lifecycle, event streaming, TUI cockpit,
web cockpit, take-over flow, and git worktrees are functional and tested.
The OpenCode driver has never been run against a live `opencode serve` —
that's the critical next step to make agentjam useful with real agents.

See [`docs/RETRO.md`](docs/RETRO.md) for an honest self-audit and
[`roadmap.md`](roadmap.md) for what's planned.

---

## License

MIT — see [`LICENSE`](LICENSE).
