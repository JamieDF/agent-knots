# Architecture

This document describes agent-knots's design at a level intended for
contributors and curious users. For the high-level "what does it do" see the
[README](../README.md).

## Goals

agent-knots is built around five goals. Each architectural decision should
serve at least one of these:

1. **You always own the session.** No dead-end states. Control transfers
   both ways, at any moment (the autonomous toggle).
2. **Model-agnostic.** One abstraction layer over OpenAI-compatible APIs,
   Ollama, MiniMax, GLM, Anthropic, anything else — via LiteLLM/OpenAI
   clients under the Strands Agents SDK.
3. **Local-first.** Everything lives on disk under `~/.agent-knots/`. No
   required cloud sync.
4. **Multi-agent from day one.** Concurrent sessions, sub-agent delegation,
   and advisory roles sharing a task are all first-class concepts.
5. **State is outside the agent.** Tasks, progress, credentials, projects —
   all persistent structured objects, never just chat scrollback.

## High-level diagram

```
┌─ agent-knots ────────────────────────────────────────────┐
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
│   │  InProcessRuntime · git branch per session            │   │
│   │  ┌──────────────────────────────────────────────┐  │   │
│   │  │  Strands Agent (MiniMax/OpenAI/Anthropic/...)  │  │   │
│   │  │  Tools: editor, shell, calculator, think,      │  │   │
│   │  │         8 task tools, custom tools              │  │   │
│   │  │  Sandbox: cwd isolation + path traversal guard │  │   │
│   │  └──────────────────────────────────────────────┘  │   │
│   └──────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

## Package layout

```
agent-knots/
├── frontend/                     # Vite + React SPA (web cockpit, "Atelier")
│   └── src/
│       ├── views/                 # Dashboard, Tasks (Board+List tabs), TaskDetail,
│       │                          # AgentThread, Review, Workflows, Settings (incl. Vault)
│       ├── components/            # Topbar, TaskDialog, WorkspaceDialog/Switcher,
│       │                          # NewSessionDialog, Markdown, primitives/, ...
│       └── lib/                   # API client, SSE client, workspace context
├── src/agent_knots/
│   ├── cli/                       # Typer CLI entry point + commands
│   │   └── main.py
│   ├── cockpit/
│   │   ├── tui/                   # Textual TUI (overview, focus, tools)
│   │   └── web/                   # FastAPI server (auth, SSE, REST, SPA shell)
│   ├── session/
│   │   ├── manager.py             # SessionManager, Session, system prompt assembly
│   │   ├── runtime.py             # SessionRuntime, InProcessRuntime
│   │   └── features.py            # memory injection, multi-agent delegate, steering
│   ├── task/                      # Task model, YAML store, Strands tools for agents
│   ├── project/                   # Workspace model + YAML store
│   ├── vault/                     # AES-256-GCM crypto + file store
│   ├── tools/                     # Tool registry, defaults, custom tools
│   ├── workflows/                 # Board stage config + agent role config (incl. advisory roles)
│   ├── policies/                  # Config toggles for the Settings screen
│   ├── config.py                  # Data-directory paths (AGENT_KNOTS_HOME resolution)
│   ├── settings.py                # Global YAML settings store
│   ├── provider.py                # Model provider resolution (CLI/env/settings)
│   ├── isolation.py               # WorkspaceSandbox — cwd confinement config
│   ├── sandbox_tools.py           # Sandboxed shell/editor tools
│   ├── intervention.py            # Read-only tool gating for reviewer/security modes
│   ├── hooks.py                   # Token tracking + auto progress logging
│   ├── events.py                  # Event/EventType/ToolCall wire types
│   ├── gitutil.py                 # Per-session branch create/resume/teardown
│   ├── wastebin.py                # Stopped-session tombstones + retention
│   ├── mcp_servers.py             # MCP server registry (config-only, no client wiring yet)
│   └── usage.py                   # Token/cost usage ledger
├── tests/                         # Python unit tests
├── docs/                          # Architecture, quickstart
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
(mode + task context), and builds a Strands `Agent` with the tool set and a
`ModeInterventionHandler`.

`SessionRuntime` (`session/runtime.py`) has one implementation:

- **`InProcessRuntime`** runs the agent in a background `asyncio` task on
  the same process — fast, no isolation. `start()` kicks off the agent's
  first turn (via `SessionManager._run_agent`) whenever a task description
  or prompt is present; a session created with neither just sits idle
  until `send()`.

A second implementation, `SubprocessRuntime`, existed here — it spawned a
child process (`session/worker.py`) that ran the agent loop and streamed
JSONL events back over stdin/stdout, selected per workspace/session when
isolation mattered more than startup latency. It was removed rather than
fixed: its event-forwarding path referenced `session._events`, an
attribute removed when the SSE fan-out fix replaced the single queue with
`_subscribers`/`_history`/`_broadcast()`, so it raised `AttributeError` on
the first event any subprocess-runtime session tried to emit — uncaught
by any test since the default runtime is `inprocess`. Its own event-chunk
parser had also independently drifted from the fixed one in
`manager.py`.
`set_runtime_type()`/`create_runtime()` silently fall back to
`InProcessRuntime` for any unrecognized runtime value now (including a
pre-existing `"subprocess"` saved in a settings/project file from before
the removal), so an existing install doesn't break on upgrade.

The abstraction is still worth keeping as a real interface (rather than
inlining `InProcessRuntime` directly into `SessionManager`) specifically
so a *real* isolated runtime — container-backed, most likely, see the
roadmap — can be added later without changing `SessionManager`'s own
code, only `create_runtime()`.

`SessionManager.start()` resolves which one to use via `create_runtime()`
for both paths — there's no special-casing of either runtime type.
`InProcessRuntime` used to be dead code, with the in-process path
bypassing the `SessionRuntime` abstraction entirely; that asymmetry is
fixed now.

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
(`log_progress`, `update_task_status`, `mark_criterion_met`, `add_step`,
...) after meaningful actions. `session/features.py` also injects recent
progress from earlier sessions on the same task into the system prompt
(`inject_memory`), so a new session picks up where the last one left off.

**Acceptance criteria are enforced, not advisory.** `Task.criteria_met`
tracks which acceptance criteria have been explicitly marked satisfied via
`mark_criterion_met`. `TaskStore._validate_transition` refuses to move a
task to `done` (via either `set_status` or a status-carrying
`log_progress` call) until every criterion is in that list. The steering
hook's keyword-match against tool output is advisory only — it suggests a
criterion might be met, it never marks one itself — so a fuzzy match can't
quietly satisfy the gate.

### Project

A workspace record (`project/models.py`, `project/store.py`) bundling one
or more repos with project-level settings and a task namespace. Selecting a
project scopes task listing and session workspace resolution.

### Session branches

A task-attached session gets its own git branch (`gitutil.py`), named from
the task's title plus a short hash of its id for uniqueness
(`knots/<slugified-title>-<hash>`). The branch is created on first start
and reused on every later resume of the same task, so a second session
picking up old work checks out exactly what the first session left behind
rather than starting fresh off the base branch. A branch is only deleted
automatically if it ends up with zero commits and a clean working tree
(`gitutil.delete_branch_if_empty`) — an agent's uncommitted work is never
silently discarded by session teardown.

### Wastebin

Every `SessionManager.stop()` call, automatic or manual, writes a
tombstone record (`wastebin.py`): task, branch, tokens, cost, and whether
the session's working directory was one of the app's own auto-provisioned
ones (only those get cleaned up on delete — a real repo path never does).
A session auto-stops once its task reaches `review`, `done`, or
`abandoned`. Wastebin entries are individually deletable and swept by a
configurable retention setting; deleting an entry never force-deletes a
branch a newer entry or a still-active session legitimately references.

### Multi-agent

Beyond `delegate_task` (an agent spawning its own sub-agent on a
sub-task), a `Role` (`workflows/models.py`) can be marked `advisory`,
meaning it shares an existing task's session rather than starting its
own: a read-only reviewer role, for instance, runs alongside the task's
main writer session with a restricted tool allowlist
(`Session.allowed_tools`) rather than write access.

### WorkspaceSandbox

Per-session isolation (`isolation.py`, `sandbox_tools.py`). Rather than a
container boundary, each session gets a `WorkspaceSandbox` that:

- confines the **editor** tool to the workspace root via real path
  resolution (traversal, including symlink escapes, is rejected);
- gives the **shell** tool a default `cwd`, a CPU-time resource limit, and
  full process-group cleanup on timeout via `sandbox_tools.run_confined`
  — **not** command-level path confinement, since that's not achievable
  for an arbitrary `shell=True` string without real OS-level sandboxing.
  There used to also be an `RLIMIT_AS` (virtual address space) memory
  cap, removed after it turned out to be the wrong lever entirely:
  modern runtimes like Node/V8 reserve several GB of *virtual* address
  space upfront regardless of actual memory used, so any cap small
  enough to matter made every `npm`/`vite`/`node` command an agent tried
  crash immediately with an OOM error, real memory pressure or not;
- lets the shell tool start a command with `background=true` for
  anything meant to outlive the tool call (dev servers, watchers) — see
  "Background processes" above;
- truncates shell output past `max_output` and rejects editor writes past
  `max_file_size`, both configurable on `WorkspaceSandbox`.

Full container-based isolation (podman/Docker) is a roadmap item, not yet
implemented.

### Tool registry

`tools/registry.py` tracks built-in tools (editor, shell, calculator,
think, plus 8 task tools) and user-defined custom shell-command tools
persisted to `~/.agent-knots/settings.yaml`. Each session's `Agent` is built
from whichever tools are currently enabled.

### Mode

A short label (`agent`, `assistant`, `reviewer`, `security`) that selects a
canned system-prompt fragment, assembled in
`session/manager.py::_build_system_prompt`. Unlike the original Go design,
which loaded per-mode system prompts from markdown files via a Pi
extension, modes are inline string fragments in `manager.py` — no external
files are read. Mode swapping at runtime (assume/relinquish) is
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
  - hands off to InProcessRuntime
                │
                ▼
Events stream from the runtime as an asyncio.Queue (TUI) or are broadcast
over SSE (web) as structured JSON — `events.py::serialize_event()`, not
pre-rendered HTML (that coupling was removed as part of the Atelier
frontend rewrite; the frontend now owns all event rendering):
  - message / thinking events
  - tool_call / tool_result events
  - auto_log events (auto-logged by hooks)
  - steer events (steering-hook nudges)
  - delegate events (sub-agent started — carries the sub-session/task id)
  - checkpoint events (marker only — no real revert, see roadmap)
  - blocker events (agent flagged something needing human input)
  - user / state_change / ended events (session lifecycle)
  - error events (agent-loop exceptions)
                │
                ▼
Agent calls task tools (log_progress, update_task_status, ...) as it works.
Session ends on completion, error, or explicit stop.
```

### Autonomous toggle

`SessionManager.set_autonomous(session_id, on)` (`POST /api/agent/{id}/
autonomous`) is the web UI's single on/off switch for a task-attached
session, replacing the older separate Assume/Relinquish actions:

- **Off** — interrupts whatever's currently running (`interrupt()`) and
  sets `mode = "assistant"`, so the session stops self-continuing the
  task until switched back on. Tool calls still work in this mode — see
  below, this is *not* the same thing as the reviewer/security read-only
  gate.
- **On** — sets `mode = "agent"` and, if the session has a `task_id`,
  sends a "resume working on the task" nudge via `send()` so it actually
  picks the task back up rather than just flipping a label.

`SessionManager.set_mode()` is the lower-level primitive underneath this
(still directly reachable via `POST /api/agent/{id}/assume`/`relinquish`
for a raw mode flip with no interrupt/resume behavior) — it just sets
`session.mode`. It does **not** gate tool calls for `agent`/`assistant`;
only `ModeInterventionHandler` (`intervention.py`) does that, and only
for `reviewer`/`security` modes (CLI-only, not exposed in the web UI).
An earlier version of this doc — and an earlier version of the code —
had `assistant` mode denying every tool call via the same handler; that
turned out not to be the wanted behavior (a paused session should still
be able to act on what you tell it, just not keep self-directing on its
own), and the handler was also just plain broken for anything it
tried to gate.

### Interrupt vs stop

Two different ways to end an agent's current activity, easy to conflate:

- **`SessionManager.interrupt()`** (`POST /api/agent/{id}/interrupt`)
  cancels only the currently-running turn — `Session.cancel(end_session=
  False)` sets `_interrupt_only`, so `_run_agent`'s cancellation handler
  broadcasts `STATE_CHANGE` instead of `ENDED`. The session stays in
  `SessionManager._sessions`; a follow-up `send()` starts a new turn on
  the same conversation. This is what the Agent Thread composer's "■
  Stop" button calls, and it only appears while the agent is actually
  running.
- **`SessionManager.stop()`** (`DELETE /api/agent/{id}`) ends the session
  for good — pops it out of `_sessions`, cancels with `end_session=True`
  (broadcasts `ENDED`), and kills any background processes the session
  tracked (see below). This is the header "✕ Delete" button.

### Background processes

`sandbox_tools.run_background()` (used by the sandboxed shell tool's
`background=true` argument) starts a command detached — via `os.setsid()`
and no `Popen.wait()`/timeout — for anything meant to outlive a single
tool call (dev servers, watchers). Its pid is appended to a
`background_pids` list that's handed to both the shell-tool closure and
the owning `Session` (`_background_pids`) at construction time, so
`SessionManager.stop()` can kill (`kill_background_process()`, which also
reaps the pid to avoid a zombie) every background process a session
started when the session itself ends. `interrupt()` does *not* touch
these — they're explicitly meant to survive a single-turn cancellation,
only the session's own teardown cleans them up.

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

- **Multiple sessions run independently**, each owning its own
  in-process `asyncio` task.
- **The web server is async** (FastAPI + `asyncio`); each connected
  browser tab gets its own SSE subscriber queue via `Session.subscribe()`,
  fanned out from a shared per-session event history/broadcast
  (`Session._broadcast()`) — fixed from an earlier single-queue design
  where a second tab watching the same agent would race the first for
  events and silently lose some.
- **The TUI polls an `asyncio.Queue`** per focused session.

The orchestrator is single-process today — every session's runtime lives
in the same Python process. Real process-level isolation (and the
multi-process fan-out it would enable, e.g. a daemon coordinating
multiple hosts) is out of scope until the container runtime on the
roadmap lands.

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
