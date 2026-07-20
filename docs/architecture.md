# Architecture

This document describes agent-knots's design at a level intended for contributors
and curious users. For the high-level "what does it do" see the
[README](../README.md). For the rationale behind specific decisions, see the
decision records in [`docs/decisions/`](decisions/).

## Goals

agent-knots is built around five goals. Each architectural decision should serve
at least one of these:

1. **You always own the session.** No dead-end states. Control transfers
   both ways, at any moment.
2. **Model-agnostic.** One abstraction layer over OpenAI-compatible APIs,
   Ollama, MiniMax, GLM, Anthropic, anything else.
3. **Local-first.** Everything lives on disk. No required cloud sync.
4. **Multi-agent from day one.** Concurrent sessions are a first-class concept.
5. **State is outside the agent.** Tasks, progress, credentials, projects —
   all persistent structured objects, never just chat scrollback.

## High-level diagram

```
┌─ User machine ──────────────────────────────────────────────────────────┐
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Orchestrator (this repo)                                           │ │
│  │                                                                     │ │
│  │  ┌─────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐│ │
│  │  │   Driver    │ │  Vault   │ │  Task   │ │ Project  │ │  Modes   ││ │
│  │  │ interface   │ │ (AES)    │ │ (YAML)  │ │  (YAML)  │ │(markdown)││ │
│  │  └─────────────┘ └──────────┘ └─────────┘ └──────────┘ └──────────┘│ │
│  │         │            │            │            │             │      │ │
│  │         └────────────┴────────────┴────────────┴─────────────┘      │ │
│  │                              │                                     │ │
│  │  ┌───────────────────────────▼───────────────────────────────┐   │ │
│  │  │ Cockpit (Web GUI primary + TUI)                           │   │ │
│  │  │ • Multi-agent list     • Per-agent focus                  │   │ │
│  │  │ • Live event stream    • Take over / relinquish          │   │ │
│  │  │ • Task management      • Vault management                │   │ │
│  │  └─────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
                  │                              │
                  │ Go SDK                       │ HTTP / WebSocket
                  ▼                              ▼
       ┌──────────────────┐         ┌────────────────────────┐
       │ Local OpenCode   │         │ Containerized OpenCode │
       │ (subprocess)     │         │ (Podman)               │
       └──────────────────┘         └────────────────────────┘
```

## Package layout

```
agent-knots/
├── cmd/
│   └── agent-knots/                # CLI entry point
│       ├── main.go             # root cobra command
│       ├── project.go          # project subcommand
│       ├── task.go             # task subcommand
│       ├── vault.go            # vault subcommand
│       ├── agent.go            # agent subcommand
│       ├── cockpit.go          # cockpit subcommand
│       └── prompt.go           # structured task prompt builder
├── internal/
│   ├── agent/
│   │   ├── driver/             # AgentDriver interface + event types
│   │   └── driver/opencode/    # OpenCode Go SDK implementation
│   ├── config/                 # AGENT_KNOTS_HOME resolution
│   ├── container/              # ContainerRuntime interface
│   ├── container/podman/       # Podman implementation
│   ├── errs/                   # sentinel errors
│   ├── mode/                   # Mode loader (markdown → system prompt)
│   ├── project/                # Project schema + Store interface
│   ├── project/filestore/      # YAML file-backed project store
│   ├── task/                   # Task schema + Store interface
│   ├── task/filestore/         # YAML file-backed task store
│   ├── vault/                  # Vault interface + Template types
│   └── vault/filestore/        # AES-256-GCM encrypted vault
├── modes/                      # Default mode markdown files
└── docs/                       # Architecture, contributing, etc.
```

All implementation lives under `internal/`. Only packages in `cmd/` and a
small set of stable interfaces are intended for external consumption. This
gives us the freedom to refactor internals without breaking downstream
consumers.

## Core abstractions

### AgentDriver

The most important interface in the project. Every agent backend
(OpenCode today, custom drivers tomorrow) implements it. The orchestrator
holds only a `Driver`; it doesn't know or care which backend is underneath.

```go
type Driver interface {
    Start(ctx context.Context) error
    Stop(ctx context.Context) error
    Send(ctx context.Context, msg Message) error
    Events() <-chan Event
    Snapshot(ctx context.Context) (State, error)
    SetMode(ctx context.Context, mode Mode) error
    Pause(ctx context.Context) error
    Resume(ctx context.Context) error
    Abort(ctx context.Context) error
    ID() string
}
```

**Why this matters:** the entire orchestrator — cockpit, task system, vault
integration — talks to drivers through this interface. To add a new agent
backend, implement this interface; nothing else needs to change.

**Where the interface lives:** in `internal/agent/driver/`. By Go convention,
interfaces are defined where they're *used*, not where they're implemented.
Today, both the orchestrator and the implementations live in this repo, but
in the future implementations could move out without changing the interface.

### Vault

Stores credentials encrypted at rest. The agent uses credentials via opaque
`vault://` URIs and never sees raw values. Injection templates control how
credentials are exposed (env vars, files, stdin, command wrappers).

**Security model:**
- Credentials are AES-256-GCM encrypted with a per-entry key derived from
  the vault master key.
- The vault master key is derived from the user's passphrase via argon2id.
- The credential value never crosses the vault boundary except into the
  spawned subprocess.
- Stdout and stderr are scrubbed of credential values before being returned.
- Every use is logged to an append-only audit log.

**Why templates, not direct use:** the agent can't see the credential, and
*how* it's exposed is per-tool (env for `gh`, file for SSH keys, stdin for
`jira-cli`, command wrapper for `curl`). Templates let the user declare this
declaratively, and the agent picks the right one via name.

### Task

A persistent work record with structured progress logs. The agent calls
`task_log_progress` after every meaningful action. The progress log is the
recovery point — if context is lost, the next agent reads the log and picks
up where the previous one left off.

**Why this exists:** without structured progress logging, agentic tasks get
abandoned when context is lost or the model is swapped. The progress log
turns "agent state" into an external, queryable, inspectable artifact.

**Anti-abandonment mechanisms:**
- The agent *must* call `task_log_progress` after every meaningful action.
- On context compaction, the agent-knots summarizes the conversation into a
  progress entry *before* trimming, so compaction never loses task state.
- If a task is `in_progress` with no log entry for N hours, it's flagged
  as `stalled` and surfaced in the cockpit.
- Acceptance criteria gate `done` — every criterion must be verified with
  evidence before the task can transition.

### Project

A multi-repo workspace. A project bundles N git repos into one logical unit
with project-level settings: build commands, conventions, vault scope,
default models, and a task namespace.

**Why this matters:** agents need context. "What does this project use for
testing?" "What conventions should I follow?" "Which credentials can I use?"
The project file is where these answers live, and switching projects swaps
the entire context.

### Mode

A named system prompt that controls agent behavior. Modes live as markdown
files in `~/.agent-knots/modes/` and are loaded by name. The same driver
implements every mode; only the system prompt changes.

**Why this exists:** different tasks want different agent personalities.
An agent working autonomously should be decisive and verbose in its progress
log; a reviewer should be read-only and structured in its findings. Modes
encode these behavioral differences as data (markdown), not code.

### ContainerRuntime

Abstraction over container engines. v1 implements Podman; the interface is
defined so future runtimes (Docker, Apple Container, etc.) plug in without
changes elsewhere.

**Why an abstraction:** different teams have different container tools. By
defining the interface once and configuring the runtime in settings, users
choose their tool without us maintaining N implementations.

## Data flow

### Spawning an agent on a task

```
User runs: agent-knots agent spawn --task T-001 --mode agent
                │
                ▼
CLI resolves:
  - task T-001 → project P-001, workspace /home/user/work/my-app
  - mode agent → loads modes/agent.md → system prompt
                │
                ▼
CLI constructs OpenCode driver via SDK:
  - client := opencode.NewClient(...)
  - session := client.Session.New(ctx, ...)
                │
                ▼
Driver.Start(ctx) — session established
Driver.SetMode(ctx, "agent") — system prompt applied
Driver.Send(ctx, message{role:"user", content:buildTaskPrompt(T-001)})
                │
                ▼
Events stream from driver.Events():
  - message events → cockpit / stdout
  - tool_call events → executed by OpenCode
  - tool_result events → returned to user
  - state_change events → status updated
  - error events → surfaced
                │
                ▼
Agent calls task_log_progress after each meaningful action
Agent calls task_check_acceptance before transitioning to done
                │
                ▼
Session ends:
  - User: Ctrl-C → driver.Stop(ctx)
  - Agent: idle / blocked / done → graceful close
```

### Using a credential

```
Agent wants to push to GitHub:
  agent calls vault_use({
    credential: "vault://github/work",
    template: "gh_cli_env",
    command: "gh",
    args: ["pr", "create", "--fill"]
  })
                │
                ▼
Orchestrator routes to Vault.Use():
  - lookup credential "github/work"
  - lookup template "gh_cli_env"
  - decrypt credential value (in-memory only)
  - apply template injection:
      env = { "GH_TOKEN": "ghp_..." }
  - exec.Command("gh", "pr", "create", "--fill", env=env)
  - capture stdout / stderr
  - scrub credential value from outputs
  - write audit entry: { timestamp, credential, template, command, caller, success }
  - return UseResult (no credential value)
                │
                ▼
Agent sees:
  {
    stdout: "https://github.com/org/repo/pull/123",
    stderr: "",
    exit_code: 0
  }
```

The credential value never left the vault boundary. The agent saw the PR
URL, the vault saw the token. The audit log records that the agent
("agent:auth-fix") used github/work with gh_cli_env to run `gh pr create`.

## Security model

### Threat model

agent-knots is a personal tool. The user is the operator, the agent is the
assistant. Threats:

1. **Credential leakage.** A bug or LLM hallucination causes a credential
   to appear in logs, transcripts, or agent-visible output.
2. **Destructive actions.** The agent runs `rm -rf` on the wrong directory.
3. **Cross-project contamination.** Credentials or settings from one project
   leak into another.
4. **Vault compromise.** An attacker with file-system access recovers the
   vault contents.

### Mitigations

1. **Credential leakage:** scrubbing on every output path, opaque references
   (`vault://`), templates that move the secret directly into a child
   process without going through the agent.
2. **Destructive actions:** risk policies per project
   (`require_approval_for`, `blocked_commands`), container isolation for
   long-running agents, vaults that don't store write tokens.
3. **Cross-project contamination:** vault scope per project
   (`allowed_credentials`, `denied_credentials`).
4. **Vault compromise:** AES-256-GCM with argon2id-derived keys, OS keychain
   integration, per-entry keys (compromise of one entry doesn't expose the
   master).

### Audit

The vault's audit log is append-only. Every credential use is recorded with
timestamp, credential, template, command, caller, and success. The log is
not editable from the orchestrator.

## Concurrency

agent-knots is designed for concurrent agents:

- **Multiple drivers run in parallel.** Each driver is independent; the
  cockpit manages N of them.
- **Shared state is guarded by mutexes.** The vault, task store, and project
  store all use internal locking.
- **Events are delivered on channels.** Each driver's `Events()` returns a
  channel; the cockpit reads from N channels concurrently (one goroutine
  per agent).

The orchestrator is single-process for v1. Multi-process or distributed
deployment is out of scope until a use case demands it.

## Extensibility

### Custom drivers

Implement `driver.Driver`. The orchestrator doesn't care which backend is
underneath. Add the new implementation under `internal/agent/driver/<name>/`
and wire it into the spawn command.

### Custom modes

Drop a markdown file in `~/.agent-knots/modes/<name>.md`. The mode loader picks
it up automatically. First line becomes the display name; rest is the system
prompt.

### Custom vault templates

`agent-knots vault template add <cred-id> --name <tname> --env '{...}'` — see
`agent-knots vault template add --help` for all injection modes.

### Custom container runtimes

Implement `container.Runtime`. Plug into settings.

## What's not in scope (v1)

- Multi-user support (single user, local install)
- Cloud sync (local only)
- Web GUI beyond a stub (TUI cockpit is the v1 UI surface)
- Distributed agent orchestration
- Mobile companion app

## Future work

See [`docs/roadmap.md`](roadmap.md).