# AgentJam

> Local-first orchestrator for AI coding agents. You stay in control.

AgentJam is a platform for running, observing, and orchestrating multiple AI
coding agents in parallel across multi-repo projects. It ships with:

- **A unified driver interface** so any agent backend (OpenCode today, custom
  drivers tomorrow) plugs in cleanly.
- **A persistent task system** with progress logs that survive context
  compaction, agent crashes, and mode swaps.
- **A credential vault** with injection templates — the agent uses
  `vault://github/personal` without ever seeing the token.
- **Containerized agents** that run in Podman, work on a repo, run tests, and
  open a PR — all in isolation.
- **Multi-repo project workspaces** that bind N git repos into one logical unit.
- **Two UI surfaces** — a Web GUI (primary) and a TUI (keyboard-driven, SSH-friendly).
- **Mode-based behavior** — `assistant`, `agent`, `reviewer`, etc. are just
  system prompts. The driver is the same; only the persona changes.

You always own the session. **Assume control** or **relinquish control** at any
moment. No dead-end states.

---

## Quickstart

```bash
# Install
go install github.com/agentjam/agentjam/cmd/agentjam@latest

# Initialize a new project
agentjam project init my-app --repo [email protected]:you/my-app.git

# Switch to it
agentjam project switch my-app

# Open the cockpit (TUI default, web if --gui)
agentjam cockpit

# Spawn an agent on a task
agentjam task new --title "Add dark mode toggle"
agentjam agent spawn --task T-... --mode agent
```

For a full walkthrough, see [`docs/quickstart.md`](docs/quickstart.md).

---

## Why AgentJam?

Most AI coding tools are single-agent, single-session. When you want to run
three agents in parallel — one refactoring auth, one fixing failing tests, one
reviewing a PR — you're stuck with N separate terminal tabs and no shared view
of what's happening.

AgentJam is built for that case from day one:

| Need | AgentJam |
|------|---------|
| Run multiple agents at once | ✅ Concurrent cockpit |
| See all of them at a glance | ✅ Web GUI + TUI |
| Switch between them mid-task | ✅ Keyboard-driven focus |
| Containerize an agent for a real PR | ✅ Podman + worktrees + tests |
| Use any LLM (cloud or local) | ✅ Provider-agnostic |
| Keep tasks alive across context loss | ✅ Persistent progress logs |
| Use secrets without exposing them | ✅ Vault + injection templates |
| Manage N repos as one workspace | ✅ Multi-repo projects |

---

## Architecture

```
┌─ Your laptop ─────────────────────────────────────────────┐
│                                                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Orchestrator (this repo)                           │  │
│  │  - Cockpit UI (Web + TUI)                          │  │
│  │  - Task system  - Vault  - Project workspaces      │  │
│  │  - Talks to drivers via AgentDriver interface      │  │
│  │  - Manages N drivers concurrently                  │  │
│  └──────┬───────────────────────────────────────────┬─┘  │
│         │ Go SDK        │ HTTP/WS to container A  │     │
│         │               │ HTTP/WS to container B  │     │
└─────────┼───────────────┼──────────────────────────┼─────┘
          ▼               ▼                          ▼
   ┌─────────────┐ ┌─────────────┐           ┌─────────────┐
   │ Local       │ │ Container   │           │ Container   │
   │ Driver      │ │ A Driver    │           │ B Driver    │
   │ (OpenCode)  │ │ (port 7001) │           │ (port 7002) │
   └─────────────┘ └─────────────┘           └─────────────┘
```

The full architecture document lives at [`docs/architecture.md`](docs/architecture.md).

---

## Status

AgentJam is in **early development (v0.1.0)**. The interfaces and core
implementations are usable; the cockpit UIs and container integration are
scaffolded but evolving.

**What's working in v0.1.0:**
- All core interfaces (`AgentDriver`, `Vault`, `TaskStore`, `ProjectStore`,
  `ContainerRuntime`, `Mode`)
- File-backed implementations of vault (AES-256-GCM), tasks (YAML), and
  projects (YAML)
- Mode loader (markdown → system prompt)
- Podman container runtime (CLI-based)
- OpenCode driver via the official Go SDK
- CLI with `project`, `task`, `vault`, `agent`, `cockpit` subcommands
- Unit tests across all core packages
- Default modes: `assistant`, `agent`, `reviewer`, `security`, `junior-dev`,
  `senior-dev`

**What's next:** see [`docs/roadmap.md`](docs/roadmap.md).

---

## Contributing

We welcome contributions. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
process, [`docs/architecture.md`](docs/architecture.md) for the design, and the
[issue tracker](../../issues) for current work.

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Acknowledgments

- [OpenCode](https://opencode.ai) — the agent engine we embed via the Go SDK
- [Bubble Tea](https://github.com/charmbracelet/bubbletea) — TUI framework
- [Cobra](https://github.com/spf13/cobra) — CLI framework
- [Podman](https://podman.io) — container runtime