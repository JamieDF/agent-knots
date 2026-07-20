# Quickstart

This walkthrough goes a bit deeper than the README's quickstart: vault,
tasks, and a full session lifecycle from the CLI.

## Prerequisites

- **Python 3.14+** and [`uv`](https://docs.astral.sh/uv/)
- **Node.js** (to build the web cockpit frontend; optional if you only use
  the TUI)
- An **LLM API key** for any OpenAI-compatible provider (MiniMax, OpenAI,
  Ollama, etc.)

## Install

```bash
git clone https://github.com/jamiedf/agent-knots.git
cd agent-knots
uv sync

# Optional: build the web cockpit frontend
cd frontend && npm install && npm run build && cd ..
```

Verify:

```bash
uv run agent-knots version
# agent-knots 0.1.0
```

## Configure a model provider

Settings resolve in this order: CLI flags → `AGENT_KNOTS_*` env vars →
`~/.agent-knots/settings.yaml`.

```bash
mkdir -p ~/.agent-knots
cat > ~/.agent-knots/settings.yaml << 'EOF'
agent:
  default_model: minimax-m2.7
  base_url: https://api.minimax.io/v1
  api_key: <your-api-key>
  runtime: inprocess
EOF
```

Or export env vars for a one-off session:

```bash
export AGENT_KNOTS_MODEL=openai/minimax-m2.7
export AGENT_KNOTS_BASE_URL=https://api.minimax.io/v1
export AGENT_KNOTS_API_KEY=<your-minimax-key>
```

All persistent state lives under `~/.agent-knots/` (override with
`AGENT_KNOTS_HOME=/some/path`). Subdirectories (`sessions/`, `tasks/`,
`projects/`, `vault/`) are created on first use.

## Initialize the vault

```bash
uv run agent-knots vault init
# Choose a passphrase: ********
# Confirm passphrase: ********
# Vault initialized and unlocked.
```

Lock it with `agent-knots vault lock`, unlock with `agent-knots vault
unlock`.

## Add a credential

```bash
uv run agent-knots vault add github-work --description "GitHub PAT for work" --tag github --tag work
# Credential value: ********
# Confirm value: ********
# Credential 'github-work' added.

uv run agent-knots vault list
uv run agent-knots vault audit
```

Credentials are encrypted at rest (AES-256-GCM, argon2id-derived keys).
Attach an injection template so a tool knows how to consume it:

```bash
uv run agent-knots vault template add github-work \
  --name gh_cli_env --env '{"GH_TOKEN": "$value"}'

uv run agent-knots vault template list github-work
uv run agent-knots vault template show github-work gh_cli_env
```

> Templates are stored metadata today — there's no agent-callable
> `vault_use` tool yet that spawns a command with the injection applied
> and scrubs the output. That execution engine is on the
> [roadmap](../roadmap.md). See
> [`examples/templates/`](../examples/templates/) for a library of
> starter templates.

## Create a project

```bash
uv run agent-knots project create my-app \
  --name "My App" --repo "[email protected]:me/my-app.git"
# Project created: my-app

uv run agent-knots project list
uv run agent-knots project show my-app
```

## Create a task

```bash
uv run agent-knots task create "Add dark mode toggle to settings" \
  --project my-app \
  --priority medium \
  --criteria "Toggle visible in /settings/appearance" \
  --criteria "Choice persists across sessions"
# Task created: T-...
```

```bash
uv run agent-knots task list
uv run agent-knots task show T-...
```

## Start a session

```bash
uv run agent-knots session start --task T-... --mode agent \
  --prompt "Add the dark mode toggle described in the task."
```

The session runs in the foreground and streams events to your terminal.
(`--detach` is not implemented yet — use the cockpit, below, to run
multiple sessions and monitor them without blocking your shell.)

```bash
uv run agent-knots session list
```

## Watch progress

```bash
uv run agent-knots task show T-...
```

The task's progress log fills in as the agent logs each meaningful action
(this happens automatically via hooks — no manual `log_progress` calls
needed from a well-behaved agent).

## Launch the cockpit

```bash
# TUI (default)
uv run agent-knots cockpit launch
# → j/k navigate, Enter focus, a assume, r relinquish, t tools, d delete, q quit

# Web
uv run agent-knots cockpit launch --web --port 8080
# → http://127.0.0.1:8080/?token=...
```

Both surfaces show live agent status, let you start new sessions, and
support assume/relinquish take-over.

## What's next?

- **Read [docs/architecture.md](architecture.md)** to understand the
  design.
- **Check [roadmap.md](../roadmap.md)** at the repo root for what's done
  and what's next.
- **Open an issue** if you find a bug or want a feature.
