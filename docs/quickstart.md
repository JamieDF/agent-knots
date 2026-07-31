# Quickstart

The GUI is the primary way to use agent-knots, and the default:
`./install.sh` then `agent-knots launch` gets you a setup wizard in the
browser with no manual config. This walkthrough goes a bit deeper than
that: vault, tasks, and a full session lifecycle from the CLI, for
scripting and automation.

## Prerequisites

- `git`, and either an internet connection for `install.sh` to fetch
  [`uv`](https://docs.astral.sh/uv/) or `uv` already installed
- **Node.js** (to build the web cockpit frontend; skipped with a warning
  if missing — the CLI/TUI still work, but the web cockpit falls back to
  a minimal shell with no setup wizard)
- An **LLM API key** for any OpenAI-compatible provider (MiniMax,
  DeepSeek, OpenAI, Ollama, etc.)

## Install

```bash
git clone https://github.com/JamieDF/agent-knots.git
cd agent-knots
./install.sh
```

This installs `uv` if it's missing, runs `uv sync`, builds the web
frontend, and installs the `agent-knots` command globally via
`uv tool install`. Safe to re-run. Verify:

```bash
agent-knots version
# agent-knots 0.2.0
```

If you're working from source without running `install.sh` (e.g.
contributing), prefix commands with `uv run` instead — `uv run agent-knots
version`, etc.

## Configure a model provider

**Via the GUI:** `agent-knots launch` opens a setup wizard
automatically on first launch — pick a provider preset (OpenAI, MiniMax,
DeepSeek, Anthropic, Ollama, or custom), paste an API key, done. No
manual file editing.

**Via the CLI/config, e.g. for scripted installs or CI** — settings
resolve in this order: CLI flags → `AGENT_KNOTS_*` env vars →
`~/.agent-knots/settings.yaml`. Any of these also skips the GUI wizard
(it checks the same resolution order), so pre-seeding either one gives
you a "zero-touch" install:

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
export AGENT_KNOTS_MODEL=minimax-m2.7
export AGENT_KNOTS_BASE_URL=https://api.minimax.io/v1
export AGENT_KNOTS_API_KEY=<your-minimax-key>
```

All persistent state lives under `~/.agent-knots/` (override with
`AGENT_KNOTS_HOME=/some/path`). Subdirectories (`sessions/`, `tasks/`,
`projects/`, `vault/`) are created on first use.

## Initialize the vault

```bash
agent-knots vault init
# Choose a passphrase: ********
# Confirm passphrase: ********
# Vault initialized and unlocked.
```

Lock it with `agent-knots vault lock`, unlock with `agent-knots vault
unlock`. Everything below also works from the web cockpit — Settings has
a Vault section with the same unlock/credentials/audit-log flow.

## Add a credential

```bash
agent-knots vault add github-work --description "GitHub PAT for work" --tag github --tag work
# Credential value: ********
# Confirm value: ********
# Credential 'github-work' added.

agent-knots vault list
agent-knots vault audit
```

Credentials are encrypted at rest (AES-256-GCM, argon2id-derived keys).
Attach an injection template so a tool knows how to consume it:

```bash
agent-knots vault template add github-work \
  --name gh_cli_env --env '{"GH_TOKEN": "$value"}'

agent-knots vault template list github-work
agent-knots vault template show github-work gh_cli_env
```

> Templates are stored metadata today — there's no agent-callable
> `vault_use` tool yet that spawns a command with the injection applied
> and scrubs the output. That execution engine is on the
> [roadmap](../roadmap.md). See
> [`examples/templates/`](../examples/templates/) for a library of
> starter templates.

## Create a project

```bash
agent-knots project create my-app \
  --name "My App" --repo "[email protected]:me/my-app.git"
# Project created: my-app

agent-knots project list
agent-knots project show my-app
```

## Create a task

```bash
agent-knots task create "Add dark mode toggle to settings" \
  --project my-app \
  --priority medium \
  --criteria "Toggle visible in /settings/appearance" \
  --criteria "Choice persists across sessions"
# Task created: T-...
```

```bash
agent-knots task list
agent-knots task show T-...
```

## Start a session

```bash
agent-knots session start --task T-... --mode agent \
  --prompt "Add the dark mode toggle described in the task."
```

The session runs in the foreground and streams events to your terminal.
(`--detach` is not implemented yet — use the cockpit, below, to run
multiple sessions and monitor them without blocking your shell.)

```bash
agent-knots session list
```

## Watch progress

```bash
agent-knots task show T-...
```

The task's progress log fills in as the agent logs each meaningful action
(this happens automatically via hooks — no manual `log_progress` calls
needed from a well-behaved agent).

## Launch the cockpit

```bash
# Web (primary surface, default)
agent-knots launch --port 8080
# → http://127.0.0.1:8080/?token=...

# TUI
agent-knots launch --tui
# → j/k navigate, Enter focus, a assume, r relinquish, t tools, d delete, q quit
```

The web cockpit is the primary surface and gets active development. The
TUI shows live agent status and lets you start sessions, but lags behind
the web UI in features (no task screen, no multi-turn sending, no vault
UI).

## What's next?

- **Read [docs/architecture.md](architecture.md)** to understand the
  design.
- **Check [roadmap.md](../roadmap.md)** at the repo root for what's done
  and what's next.
- **Open an issue** if you find a bug or want a feature.
