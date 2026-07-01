# Quickstart

This walkthrough gets you from zero to a running agent in five minutes.

## Prerequisites

- **Go 1.23+** (for building from source; prebuilt binaries coming)
- **Podman** (for containerized agents; optional for v0.1)
- **OpenCode** (for the agent engine; optional for v0.1)
- An **LLM API key** (any OpenAI-compatible provider, including local Ollama)

## Install

From source:

```bash
git clone https://github.com/agentjam/agentjam.git
cd agentjam
go build -o ~/.local/bin/agentjam ./cmd/agentjam
export PATH=$PATH:~/.local/bin
```

Verify:

```bash
agentjam version
# agentjam 0.1.0 (commit dev)
```

## Set up data directory

agentjam stores everything under `~/.agentjam/` by default. Override with
`AGENTJAM_HOME=/some/path`.

The first run creates the directory structure:

```bash
agentjam version
ls ~/.agentjam/
# logs/  modes/  projects/  tasks/  vault/
```

## Initialize the vault

```bash
agentjam vault init
# Choose a passphrase: ********
# Confirm passphrase: ********
# Vault initialized.
```

The vault is now unlocked for this session. Lock it with `agentjam vault lock`,
unlock with `agentjam vault unlock`.

## Add a credential

```bash
agentjam vault add github/work \
  --description "GitHub PAT for work" \
  --tag github --tag work
# Value: ********
# Added credential "github/work".
```

## Add a template so the agent can use it

```bash
agentjam vault template add github/work \
  --name gh_cli_env \
  --env '{"GH_TOKEN": "$value"}'
# Added template "gh_cli_env".
```

The template tells the vault: when the agent asks to use `github/work` with
template `gh_cli_env`, expose the value as `GH_TOKEN` in the spawned
process's environment.

## Create a project

```bash
agentjam project create my-app \
  --name "My Cool App" \
  --repo [email protected]:you/my-app.git \
  --branch main \
  --role frontend
# Created project "my-app".

agentjam project switch my-app
# Switched to project "my-app".
```

For multi-repo projects:

```yaml
# Edit ~/.agentjam/projects/my-app.yaml directly for advanced config.
# See docs/architecture.md for the full schema.
```

## Create a task

```bash
agentjam task new \
  --title "Add dark mode toggle to settings" \
  --project my-app \
  --priority medium \
  --acceptance "Toggle visible in /settings/appearance" \
  --acceptance "Choice persists across sessions" \
  --acceptance "No FOUC on page reload"
# Created task "T-2026-06-30-...".
```

## Spawn an agent on the task

```bash
agentjam agent spawn --task T-2026-06-30-... --mode agent
```

The agent starts in `agent` mode (autonomous, spec-driven) and begins
working the task. Events stream to your terminal:

```
Spawned agent oc-1234567890
Streaming events (Ctrl-C to stop):
[session.created] New session
[message.updated] I'll start by reading the settings page...
[tool_call] read_file src/pages/Settings.tsx
[tool_result] ...
```

## Watch progress

```bash
agentjam task show T-2026-06-30-...
```

You'll see the task's progress log fill up as the agent logs each action.

## What's next?

- **Read [docs/architecture.md](architecture.md)** to understand the
  design.
- **Browse [modes/](../modes/)** to see the default modes. Add your own
  by dropping a markdown file in `~/.agentjam/modes/`.
- **Check [docs/roadmap.md](roadmap.md)** for what's coming next.
- **Open an issue** if you find a bug or want a feature.