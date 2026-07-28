<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/logoDark.svg">
    <img src="frontend/public/logo.svg" alt="agent-knots" width="320">
  </picture>
</p>

# agent-knots

> A self-hosted, task-based orchestrator for AI agents. You stay in control.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-520%2B%20passing-brightgreen.svg)](tests/)

agent-knots is a self-hosted, task-based orchestrator for AI agents.
Create a task, assign it to an agent, and watch it work in real time
from a browser or terminal. Take over mid-task whenever you want.
Everything is tracked against the task, not a single chat session, so
you keep hold of the bigger picture across a long-running project
instead of losing it every time a session ends.

Manage tasks across different workspaces, create custom agent workflows,
configure agent isolation, and step in to take control of the agent
whenever you need.

Built on [Strands Agents SDK](https://github.com/strands-agents/sdk-python).
Provider-agnostic: configure OpenAI, Anthropic, Ollama, or any
OpenAI-compatible API in Settings. Developed and tested against MiniMax M2.7.

---

## Quickstart

```bash
git clone https://github.com/JamieDF/agent-knots.git
cd agent-knots
./install.sh

# Launch the web cockpit (GUI is the default and primary surface).
agent-knots launch --port 8080
# → http://127.0.0.1:8080/?token=...
# First launch opens a setup wizard in the browser to configure your
# model provider (API key, model, base URL). No manual config needed.

# Or launch the TUI instead
agent-knots launch --tui
# → j/k navigate, Enter focus, a assume, r relinquish, t tools, d delete, q quit
```

`install.sh` installs [`uv`](https://docs.astral.sh/uv/) if missing, syncs
Python dependencies, builds the web frontend (needs Node.js; skipped with
a warning if not found), and installs the `agent-knots` command globally
via `uv tool install`. Safe to re-run.

**Skipping the setup wizard** (scripted installs, CI, containers): export
`AGENT_KNOTS_API_KEY` / `AGENT_KNOTS_MODEL` / `AGENT_KNOTS_BASE_URL` before
first launch, or write `~/.agent-knots/settings.yaml` directly. Either
way, `configured` is true before the wizard would even ask. See
[`docs/quickstart.md`](docs/quickstart.md) for the settings file format.

---

## Features

- **Sessions**: start and stop agents from the web UI, TUI, or CLI, each
  running in-process (container isolation is on the roadmap). Task-attached
  sessions get their own git branch, reused automatically if you resume the
  task later, and auto-stop once their task reaches review, done, or
  abandoned.
- **Multi-agent**: an advisory role (e.g. a read-only reviewer) can share a
  task alongside the main agent, and an agent can delegate a sub-task to its
  own sub-agent.
- **Live observability and control**: watch an agent's terminal, files, and
  command log in real time, not just its chat output, and take over any
  agent mid-task from a browser or terminal.
- **Tasks**: YAML-backed, Draft → Open → In Progress → Review → Done, with
  a review gate only a human can pass, dependencies, acceptance criteria,
  and a configurable Kanban board.
- **Vault**: AES-256-GCM encrypted credential store. Agents can use a
  credential in a tool call without the raw value ever appearing in their
  context.
- **Providers**: OpenAI, Anthropic, Ollama, MiniMax, or any
  OpenAI-compatible API, configurable per workspace.
- Also included: a TUI cockpit, custom shell-command tools, multi-workspace
  project grouping, and per-app accessibility settings.

See [`roadmap.md`](roadmap.md) for what's not built yet.

---

## CLI Reference

```
agent-knots
├── session
│   ├── start [--task <id>] [--project <id>] [--mode agent|assistant] [--prompt <text>]
│   └── list
├── cockpit
│   └── launch [--web] [--port 8080]
├── task
│   ├── create <title> [--priority low|medium|high|urgent] [--criteria ...]
│   ├── list [--status open] [--project <id>]
│   ├── show <id>
│   ├── update <id> [--status <s>] [--assign <agent>]
│   └── delete <id>
├── vault
│   ├── init, unlock, lock, status
│   ├── add <id> [--value ...] [--tag ...]
│   ├── list, show <id>, remove <id>
│   ├── audit [--credential <id>] [--limit <n>]
│   └── template
│       ├── add <cred-id> --name <n> [--env <json>] [--file <path>] [--wrapper <cmd>]
│       ├── list <cred-id>, show <cred-id> <name>
│       └── remove <cred-id> <name>
├── project
│   ├── create <id> --name <n> [--repo <url>] [--branch <b>] [--tag ...]
│   ├── list, show <id>
│   ├── update <id> [--name ...] [--repo ...] [--branch ...]
│   └── delete <id>
└── version
```

---

## Architecture

```
┌─ agent-knots ──────────────────────────────────────┐
│                                                   │
│   Web UI (React SPA)    TUI (Textual)             │
│       ↕ REST + SSE         ↕ asyncio.Queue        │
│   ┌────────────────────────────────────────────┐ │
│   │         FastAPI web server                  │ │
│   │  Token auth, SSE streaming, REST API        │ │
│   └────────────────┬───────────────────────────┘ │
│                    │                              │
│   ┌────────────────▼───────────────────────────┐ │
│   │     Session Manager                         │ │
│   │  InProcessRuntime · git branch per session   │ │
│   │  ┌──────────────────────────────────────┐  │ │
│   │  │  Strands Agent (any provider)          │  │ │
│   │  │  12 tools: editor, shell, task mgmt   │  │ │
│   │  │  Sandbox: cwd isolation + path guard  │  │ │
│   │  └──────────────────────────────────────┘  │ │
│   └────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

## Project layout

```
agent-knots/
├── frontend/                  # Vite + React SPA (web cockpit)
│   └── src/
│       ├── views/             # Dashboard, Tasks (Board/List), TaskDetail,
│       │                      # AgentThread, Review, Workflows, Settings
│       ├── components/        # Topbar, TaskDialog, WorkspaceDialog, Markdown, ...
│       └── lib/               # API client, SSE client, workspace context
├── src/agent_knots/
│   ├── cli/                   # Typer CLI entry point + commands
│   ├── cockpit/
│   │   ├── tui/               # Textual TUI (overview, focus, tools)
│   │   └── web/               # FastAPI server (auth, SSE, REST, SPA shell)
│   ├── session/                # SessionManager, InProcessRuntime, delegation
│   ├── task/                  # Task models, YAML store, Strands tools for agents
│   ├── vault/                 # AES-256-GCM crypto + file store
│   ├── project/               # Workspace models + YAML store
│   ├── tools/                 # Tool registry, defaults, custom tools
│   ├── wastebin.py            # Stopped-session tombstones + retention
│   ├── gitutil.py             # Per-session branch create/resume/teardown
│   ├── settings.py            # Global YAML settings store
│   ├── provider.py            # Model provider resolution (CLI/env/settings)
│   ├── isolation.py           # Workspace sandbox config
│   └── sandbox_tools.py       # Sandboxed shell/editor tools
├── tests/                     # Python unit tests (520+)
├── docs/                      # ADRs, architecture, plan
└── pyproject.toml
```

---

## Testing

```bash
# Python unit tests (520+)
uv run --with pytest pytest tests/ -q

# Playwright e2e tests (~74)
cd frontend && npx playwright test
```

A handful of the Playwright tests need a real LLM provider configured
and are expected to fail without one.

---

## Status

**Alpha, feature-complete.** Provider-agnostic; developed and tested against
MiniMax M2.7.

---

## Contributing

Contributions welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev
setup, coding conventions, and the PR process. [`roadmap.md`](roadmap.md)
tracks what's shipped and what's next. [`CHANGELOG.md`](CHANGELOG.md) has
the full history.

---

## License

MIT. See [`LICENSE`](LICENSE).
