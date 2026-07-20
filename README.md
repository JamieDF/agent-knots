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
# Install
git clone <repo>
cd agent-knots
uv sync

# Configure your model provider (MiniMax, OpenAI, etc.)
mkdir -p ~/.agent-knots
cat > ~/.agent-knots/settings.yaml << 'EOF'
agent:
  default_model: minimax-m2.7
  base_url: https://api.minimax.io/v1
  api_key: <your-api-key>
  runtime: inprocess
EOF

# Build the frontend
cd frontend && npm install && npm run build && cd ..

# Launch the web cockpit
uv run agent-knots cockpit launch --web --port 8080
# → http://127.0.0.1:8080/?token=...

# Or launch the TUI cockpit
uv run agent-knots cockpit launch
# → j/k navigate, Enter focus, a assume, r relinquish, t tools, d delete, q quit
```

---

## What works

| Capability | Status |
|---|---|
| **Session lifecycle** | ✅ Start/stop agents from GUI, TUI, or CLI |
| **Live event streaming** | ✅ SSE (web) + async event queue (TUI). Tool calls, messages, progress |
| **Web cockpit** | ✅ Vite + React SPA. Agent cards, Kanban board, task detail, settings |
| **TUI cockpit** | ✅ Textual. Agent list, focus view, tools manager, keyboard shortcuts |
| **Take-over flow** | ✅ Assume (agent → assistant) / Relinquish (assistant → agent). Mode pill updates live |
| **Multi-turn chat** | ✅ Sequential conversation with context retention |
| **Task system** | ✅ YAML-backed. Draft → Open → In Progress → Review → Done. Progress logs, acceptance criteria, steps |
| **Kanban board** | ✅ 6-column board. Expand cards, status changes, start session from card |
| **Vault** | ✅ AES-256-GCM, argon2id KDF, injection templates, audit log. Ported from Go |
| **Agent tools** | ✅ 11 built-in: editor, shell, calculator, think + 7 task tools. Custom tools via settings |
| **Task tools** | ✅ Agent can create, read, update, log progress, add steps on tasks |
| **Workspaces** | ✅ Multi-project workspaces. Task filtering, session grouping, path isolation |
| **Runtime modes** | ✅ In-process (fast) + subprocess (isolated) per workspace/session |
| **Model providers** | ✅ MiniMax, OpenAI, Anthropic, Ollama, custom. Configurable in settings |
| **Custom tools** | ✅ User-defined shell command tools. Enable/disable per tool |

---

## CLI Reference

```
agent-knots
├── session
│   ├── start [--task <id>] [--project <id>] [--mode agent|assistant]
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
┌─ agent-knots cockpit ──────────────────────────────┐
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
│   │  │  14 tools: editor, shell, task mgmt   │  │ │
│   │  │  Sandbox: cwd isolation + path guard  │  │ │
│   │  └──────────────────────────────────────┘  │ │
│   └────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

## Project layout

```
agent-knots/
├── frontend/                  # Vite + React SPA
│   └── src/
│       ├── views/             # Overview, Board, Tasks, TaskDetail, Settings, ...
│       ├── components/        # Topbar, AgentCard, CreateTaskDialog, ...
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
├── tests/                     # Python unit tests (106)
├── mockups/                   # HTML design mockups
├── docs/                      # ADRs, architecture, plan
└── pyproject.toml
```

---

## Testing

```bash
# Python unit tests (106)
uv run --with pytest pytest tests/ -q

# Playwright e2e tests (43)
cd frontend && npx playwright test

# Total: 149 tests
```

---

## Status

**Alpha, feature-complete.** Sessions, tasks, board, tools, vault, isolation,
multi-turn chat, assume/relinquish — all functional and tested. Agents run with
MiniMax M2.7 by default, configurable to any OpenAI-compatible provider.

---

## License

MIT — see [`LICENSE`](LICENSE).
