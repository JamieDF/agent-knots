<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/logoDark.svg">
    <img src="frontend/public/logo.svg" alt="agent-knots" width="320">
  </picture>
</p>

# Agent Knots

> Local-first orchestrator for AI coding agents. You stay in control.

Agent Knots runs AI coding agents in your workspace. Watch them work in real time
from a browser or terminal. Take over any agent mid-task, hand control back.
Manage tasks on a Kanban board. Agents have tools for reading/writing files,
running shell commands, and managing structured tasks with progress tracking.

Built on [Strands Agents SDK](https://github.com/strands-agents/harness-sdk) with
[MiniMax M2.7](https://platform.minimax.io) as the default model provider.
Configurable to use OpenAI, Anthropic, Ollama, or any OpenAI-compatible API.

---

## Quickstart

```bash
git clone https://github.com/jamiedf/agent-knots.git
cd agent-knots
./install.sh

# Launch the web cockpit — GUI is the primary surface.
agent-knots launch --web --port 8080
# → http://127.0.0.1:8080/?token=...
# First launch opens a setup wizard in the browser to configure your
# model provider (API key, model, base URL). No manual config needed.

# Or launch the TUI cockpit
agent-knots launch
# → j/k navigate, Enter focus, a assume, r relinquish, t tools, d delete, q quit
```

`install.sh` installs [`uv`](https://docs.astral.sh/uv/) if missing, syncs
Python dependencies, builds the web frontend (needs Node.js — skipped with
a warning if not found), and installs the `agent-knots` command globally
via `uv tool install`. Safe to re-run.

**Skipping the setup wizard** (scripted installs, CI, containers): export
`AGENT_KNOTS_API_KEY` / `AGENT_KNOTS_MODEL` / `AGENT_KNOTS_BASE_URL` before
first launch, or write `~/.agent-knots/settings.yaml` directly — either
way, `configured` is true before the wizard would even ask. See
[`docs/quickstart.md`](docs/quickstart.md) for the settings file format.

---

## What works

| Capability | Status |
|---|---|
| **Session lifecycle** | ✅ Start/stop agents from GUI, TUI, or CLI. Composer's Stop cancels only the current turn (session stays open, send another message to continue) — a separate header Delete ends the session for good |
| **Live event streaming** | ✅ SSE (web) + async event queue (TUI). Fanned out to every subscriber — multiple browser tabs on the same agent don't race for events. Tool calls, messages, progress |
| **Web cockpit** | ✅ Vite + React SPA ("Atelier"). Dashboard, Tasks (Board/List), Task Detail, Agent Thread (chat-style, markdown, resizable layout, replay scrubber), Review, Workflows, Settings |
| **Agent Thread right rail** | ✅ Real interactive terminal (PTY + xterm.js) in the agent's working directory, a Files tab with previews, a Command Log (every shell invocation + timestamp), and a multi-tab Browser (address bar, open/close tabs, chat links open in a new tab) |
| **Background processes** | ✅ Agents can start a dev server or other long-running process with `background=true` — it isn't killed by the tool's timeout, and is cleaned up automatically when the session ends |
| **TUI cockpit** | ✅ Textual. Agent list, focus view, tools manager, keyboard shortcuts |
| **Take-over flow** | ✅ Assume (agent → assistant) / Relinquish (assistant → agent). Mode pill updates live; typing a message while watching assumes control automatically |
| **Multi-turn chat** | ✅ Sequential conversation with context retention |
| **Task system** | ✅ YAML-backed. Draft → Open → In Progress → Review → Done, with an enforced review gate (only a human can pass a task through review — an agent can't self-approve its own work) and task dependencies (blocked from starting until dependencies are done). Progress logs, acceptance criteria (human or agent can mark met), steps |
| **Kanban board** | ✅ Configurable stages (Workflows screen), drag-and-drop between columns, all task statuses covered |
| **Vault** | ✅ AES-256-GCM, argon2id KDF, injection templates, audit log. Full web UI (a Settings section) alongside the CLI |
| **Agent tools** | ✅ 12 built-in: editor, shell, calculator, think + 8 task tools. Custom tools via settings |
| **Task tools** | ✅ Agent can create, read, update, log progress, add steps on tasks |
| **Workspaces** | ✅ Multi-project workspaces. Task filtering, session grouping, path isolation, archive/unarchive |
| **Runtime modes** | ✅ In-process (fast) + subprocess (isolated) per workspace/session |
| **Model providers** | ✅ MiniMax, OpenAI, Anthropic, Ollama, custom. Configurable in settings |
| **Custom tools** | ✅ User-defined shell command tools. Enable/disable per tool |
| **Accessibility** | ✅ App-wide font size and font family, in Settings |

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
│   │  InProcessRuntime or SubprocessRuntime      │ │
│   │  ┌──────────────────────────────────────┐  │ │
│   │  │  Strands Agent (MiniMax/OpenAI/...)   │  │ │
│   │  │  12 tools: editor, shell, task mgmt   │  │ │
│   │  │  Sandbox: cwd isolation + path guard  │  │ │
│   │  └──────────────────────────────────────┘  │ │
│   └────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

## Project layout

```
agent-knots/
├── frontend/                  # Vite + React SPA ("Atelier" web cockpit)
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
│   ├── session/               # SessionManager, InProcess/Subprocess runtime, worker
│   ├── task/                  # Task models, YAML store, Strands tools for agents
│   ├── vault/                 # AES-256-GCM crypto + file store
│   ├── project/               # Workspace models + YAML store
│   ├── tools/                 # Tool registry, defaults, custom tools
│   ├── settings.py            # Global YAML settings store
│   ├── provider.py            # Model provider resolution (CLI/env/settings)
│   ├── isolation.py           # Workspace sandbox config
│   └── sandbox_tools.py       # Sandboxed shell/editor tools
├── tests/                     # Python unit tests (300+)
├── mockups/                   # HTML design mockups
├── docs/                      # ADRs, architecture, plan
└── pyproject.toml
```

---

## Testing

```bash
# Python unit tests (350+)
uv run --with pytest pytest tests/ -q

# Playwright e2e tests (~74)
cd frontend && npx playwright test
```

A handful of the Playwright tests need a real LLM provider configured
and are expected to fail without one.

---

## Status

**Alpha, feature-complete.** Sessions, tasks, board, tools, vault, isolation,
multi-turn chat, assume/relinquish — all functional and tested. Agents run with
MiniMax M2.7 by default, configurable to any OpenAI-compatible provider.

---

## License

MIT — see [`LICENSE`](LICENSE).
