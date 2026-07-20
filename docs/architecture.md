# Architecture

This document describes agent-knots's design at a level intended for
contributors and curious users. For the high-level "what does it do" see the
[README](../README.md). For the rationale behind specific decisions, see the
decision records in [`docs/decisions/`](decisions/) — note some of those
predate the Python rebuild described here and record decisions made for the
original Go implementation.

## Goals

agent-knots is built around five goals. Each architectural decision should
serve at least one of these:

1. **You always own the session.** No dead-end states. Control transfers
   both ways, at any moment (assume/relinquish).
2. **Model-agnostic.** One abstraction layer over OpenAI-compatible APIs,
   Ollama, MiniMax, GLM, Anthropic, anything else — via LiteLLM/OpenAI
   clients under the Strands Agents SDK.
3. **Local-first.** Everything lives on disk under `~/.agent-knots/`. No
   required cloud sync.
4. **Multi-agent from day one.** Concurrent sessions and sub-agent
   delegation are first-class concepts.
5. **State is outside the agent.** Tasks, progress, credentials, projects —
   all persistent structured objects, never just chat scrollback.

## High-level diagram

```
┌─ agent-knots cockpit ────────────────────────────────────┐
│                                                            │
│   Web UI (React SPA)    TUI (Textual)                     │
│       ↕ REST + SSE         ↕ asyncio.Queue                │
│   ┌──────────────────────────────────────────────────┐   │
│   │         FastAPI web server                         │   │
│   │  Token auth, SSE streaming, REST API               │   │
│   └────────────────┬─────────────────────────────────┘   │
│                     │                                      │
│   ┌─────────────────▼─────────────────────────────────┐   │
│   │     SessionManager                                  │   │
│   │  InProcessRuntime or SubprocessRuntime               │   │
│   │  ┌──────────────────────────────────────────────┐  │   │
│   │  │  Strands Agent (MiniMax/OpenAI/Anthropic/...)  │  │   │
│   │  │  Tools: editor, shell, calculator, think,      │  │   │
│   │  │         7 task tools, custom tools              │  │   │
│   │  │  Sandbox: cwd isolation + path traversal guard │  │   │
│   │  └──────────────────────────────────────────────┘  │   │
│   └──────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

## Package layout

```
agent-knots/
├── frontend/                     # Vite + React SPA (web cockpit)
│   └── src/
│       ├── views/                 # Overview, Board, Tasks, TaskDetail, Settings, ...
│       ├── components/            # Topbar, AgentCard, CreateTaskDialog, ...
│       └── lib/                   # API client, SSE client, workspace context
├── src/agent_knots/
│   ├── cli/                       # Typer CLI entry point + commands
│   │   └── main.py
│   ├── cockpit/
│   │   ├── tui/                   # Textual TUI (overview, focus, tools)
│   │   └── web/                   # FastAPI server (auth, SSE, REST, SPA shell)
│   ├── session/
│   │   ├── manager.py             # SessionManager, Session, system prompt assembly
│   │   ├── runtime.py             # InProcessRuntime / SubprocessRuntime
│   │   ├── features.py            # memory, multi-agent delegate, checkpoint, steering
│   │   └── worker.py              # subprocess worker entry point
│   ├── task/                      # Task model, YAML store, Strands tools for agents
│   ├── project/                   # Workspace model + YAML store
│   ├── vault/                     # AES-256-GCM crypto + file store
│   ├── tools/                     # Tool registry, defaults, custom tools
│   ├── config.py                  # Data-directory paths (AGENT_KNOTS_HOME resolution)
│   ├── settings.py                # Global YAML settings store
│   ├── provider.py                # Model provider resolution (CLI/env/settings)
│   ├── isolation.py               # WorkspaceSandbox — cwd confinement config
│   ├── sandbox_tools.py           # Sandboxed shell/editor tools
│   ├── intervention.py            # Mode-aware tool gating (assume/relinquish)
│   ├── hooks.py                   # Token tracking + auto progress logging
│   └── events.py                  # Event/EventType/ToolCall wire types
├── tests/                         # Python unit tests
├── modes/                         # Legacy mode markdown files (not currently
│                                   # loaded — see "Mode" below)
├── mockups/                       # HTML design mockups
├── docs/                          # Architecture, decisions, quickstart
└── pyproject.toml
```

Everything under `src/agent_knots/` is importable Python; there's no
public/internal split like the old Go module had. The CLI (`agent-knots`),
web server, and TUI are all thin front ends over the same `SessionManager`.

## Core abstractions

### SessionManager / SessionRuntime

`SessionManager` (`session/manager.py`) owns the set of active `Session`
objects and is the single thing the CLI, TUI, and web server all talk to.
Starting a session resolves the model provider, assembles the system prompt
(mode + task context), builds a Strands `Agent` with the tool set and a
`ModeInterventionHandler`, and hands it to a `SessionRuntime`.

Two runtimes implement `SessionRuntime` (`session/runtime.py`):

- **`InProcessRuntime`** — runs the agent loop in the same Python process.
  Fast, no IPC overhead, default for most use.
- **`SubprocessRuntime`** — spawns a child process (`session/worker.py`)
  that runs the agent loop in isolation and streams events back over a
  pipe. Selected per workspace/session when isolation matters more than
  startup latency.

**Why this matters:** the orchestrator — cockpit, task system, vault
integration — talks to sessions through this interface regardless of
which runtime is backing them. Adding a new runtime (e.g. a container-based
one, see [Roadmap](../roadmap.md)) means implementing `SessionRuntime`; nothing
else changes.

### Vault

Stores credentials encrypted at rest (`vault/crypto.py`, `vault/store.py`,
ported from the original Go implementation). AES-256-GCM encryption, keys
derived via argon2id. Injection templates control how credentials are
exposed to shell commands the agent runs, so raw values don't need to pass
through the agent's context. Every use is recorded to an append-only audit
log.

### Task

A persistent work record with structured progress logs
(`task/models.py`, `task/store.py`, YAML-backed). Agents call task tools
(`log_progress`, `update_task_status`, `add_step`, ...) after meaningful
actions. `session/features.py` also injects recent progress from earlier
sessions on the same task into the system prompt (`inject_memory`), so a
new session picks up where the last one left off, and validates steering
criteria against tool outputs after each tool call.

### Project

A workspace record (`project/models.py`, `project/store.py`) bundling one
or more repos with project-level settings and a task namespace. Selecting a
project scopes task listing and session workspace resolution.

### WorkspaceSandbox

Per-session isolation (`isolation.py`, `sandbox_tools.py`). Rather than a
container boundary, each session gets a `WorkspaceSandbox` that the
sandboxed shell/editor tools use to resolve paths relative to the
workspace root and reject traversal outside it. Full container-based
isolation (podman/Docker) is a roadmap item, not yet implemented — see
[`docs/decisions/004-container-isolation.md`](decisions/004-container-isolation.md)
for the original design sketch.

### Tool registry

`tools/registry.py` tracks built-in tools (editor, shell, calculator,
think, plus 7 task tools) and user-defined custom shell-command tools
persisted to `~/.agent-knots/settings.yaml`. Each session's `Agent` is built
from whichever tools are currently enabled.

### Mode

A short label (`agent`, `assistant`, `reviewer`, `security`) that selects a
canned system-prompt fragment, assembled in
`session/manager.py::_build_system_prompt`. Unlike the original Go design,
modes are **not** currently loaded from the markdown files in `modes/` —
those files are left over from the prior implementation and aren't read by
any code path today. Mode swapping at runtime (assume/relinquish) is
implemented via `intervention.py`'s `ModeInterventionHandler`, which gates
tool execution rather than swapping the system prompt mid-session.

## Data flow

### Starting a session

```
User runs: agent-knots session start --task T-001 --prompt "..."
                │
                ▼
CLI resolves the model provider (CLI flags → AGENT_KNOTS_* env vars →
  ~/.agent-knots/settings.yaml) and calls SessionManager.start()
                │
                ▼
SessionManager:
  - loads task T-001 (if given) for context injection
  - assembles the system prompt (mode fragment + task context)
  - builds the tool set from ToolRegistry
  - wraps tools with sandboxed shell/editor if a workspace is set
  - registers hooks (token tracking, auto progress logging, steering)
  - constructs the Strands Agent with a ModeInterventionHandler
  - hands off to InProcessRuntime or SubprocessRuntime
                │
                ▼
Events stream from the runtime as an asyncio.Queue (TUI) or are broadcast
over SSE (web):
  - message / thinking events
  - tool_call / tool_result events
  - mode_change events (assume/relinquish)
  - progress events (auto-logged by hooks)
                │
                ▼
Agent calls task tools (log_progress, update_task_status, ...) as it works.
Session ends on completion, error, or explicit stop.
```

### Assume / relinquish

`SessionManager.set_mode()` flips `session.mode` between `agent` and
`assistant`. The `ModeInterventionHandler` (Strands intervention) checks
the current mode before every tool call: `agent` → proceed, `assistant` →
deny. This is how "taking over" a session blocks the agent's tools without
tearing down and restarting the session.

## Security model

### Threat model

agent-knots is a personal tool. The user is the operator, the agent is the
assistant. Threats:

1. **Credential leakage.** A bug or LLM hallucination causes a credential
   to appear in logs, transcripts, or agent-visible output.
2. **Destructive actions.** The agent runs something destructive outside
   its intended workspace.
3. **Cross-project contamination.** Credentials or settings from one
   project leak into another.
4. **Vault compromise.** An attacker with file-system access recovers the
   vault contents.

### Mitigations

1. **Credential leakage:** vault injection templates keep raw values out of
   the agent's context; values are only exposed to the shell command they're
   injected into.
2. **Destructive actions:** `WorkspaceSandbox` confines the sandboxed
   shell/editor tools to the session's workspace directory and rejects path
   traversal. Full container isolation is planned but not yet built.
3. **Cross-project contamination:** projects are separate YAML records with
   their own task namespace; nothing shares state across them implicitly.
4. **Vault compromise:** AES-256-GCM with argon2id-derived keys, per-entry
   keys (compromise of one entry doesn't expose the master), passphrase
   never persisted.

### Audit

The vault's audit log is append-only. Every credential use is recorded with
timestamp, credential, template, caller, and success.

## Concurrency

agent-knots is designed for concurrent agents:

- **Multiple sessions run independently**, each owning its own runtime
  (in-process task or subprocess).
- **The web server is async** (FastAPI + `asyncio`); each connected
  browser tab gets its own SSE stream reading from the session's event
  queue.
- **The TUI polls an `asyncio.Queue`** per focused session.

The orchestrator is single-process for in-process sessions; subprocess
sessions add one child process each. Multi-process fan-out beyond that
(e.g. a daemon coordinating multiple hosts) is out of scope for now.

## Extensibility

### Custom tools

Add a user-defined shell-command tool via the Settings page or
`ToolRegistry`; it's persisted to `~/.agent-knots/settings.yaml` and wrapped
as a Strands tool the next time a session starts.

### Custom runtimes

Implement `SessionRuntime` (`session/runtime.py`) and wire it into
`session/runtime.py::create_runtime`. See the roadmap for the planned
container-backed runtime.

### Model providers

Anything OpenAI-compatible works out of the box via `provider.py`.
MiniMax, OpenAI, Anthropic, and Ollama are all just base-URL + API-key
combinations; no per-provider code is needed unless you want a non-OpenAI-
compatible SDK.

## What's not in scope (yet)

- Container-based isolation (planned — see [roadmap](../roadmap.md))
- Multi-user support (single user, local install)
- Cloud sync (local only)
- Distributed / multi-host orchestration

## Future work

See [`roadmap.md`](../roadmap.md) at the repo root for what's done and
what's next.
