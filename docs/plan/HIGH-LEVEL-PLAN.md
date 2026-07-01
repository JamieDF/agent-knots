# Orchestrator — High-Level Plan

> Status: **High-level scope, pre-breakdown.** Decisions locked in are marked ✅. Open questions are flagged ⚠️. Names are placeholders — final name TBD.

A local-first platform for orchestrating multiple AI coding agents across multi-repo projects. You stay in control: chat with one agent, watch ten others work autonomously, take over any of them, hand control back. Free, model-agnostic, works with any OpenAI-compatible or local model.

---

## 1. Core Philosophy

- **You always own the session.** No dead-end states. Control transfers both ways, at any time.
- **Model-agnostic.** One abstraction layer over OpenAI-compatible APIs, Ollama, MiniMax, GLM, Anthropic, anything else.
- **Local-first.** Everything lives on your disk. No required cloud sync, no vendor lock-in. Online sync is a future possibility, not v1. ✅
- **Multi-agent from day one.** Not "single agent plus a UI" — concurrent sessions are a first-class concept.
- **State is outside the agent.** Tasks, progress, credentials, projects — all persistent structured objects, never just chat scrollback.

---

## 2. Provider Abstraction Layer

**What it does:** Normalize all LLM interactions behind a single interface so the rest of the system doesn't care which model is being used.

### Features

- Unified chat API: send messages, receive streaming deltas, parse tool calls
- Configurable per-provider: base URL, API key, model name, request format
- Model listing / availability probe per provider
- Token counting + cost estimation (for paid APIs)
- Fallback / failover chain (try primary, fall back to secondary on error/rate limit)
- Streaming + non-streaming modes
- Tool-use / function-calling support per provider's convention

### Supported providers (v1)

- OpenAI-compatible REST API (most cloud providers plug in here)
- Ollama (local)
- LM Studio (local)
- MiniMax ✅ (M3)
- GLM (Zhipu)
- Anthropic (Claude) — needs its own adapter, not OpenAI-compatible
- OpenRouter (aggregator)
- Custom providers via plugin config

### Per-project provider preferences

Different providers can be the default for different project types — or even different tasks within a project (e.g., cheap model for summarization, big model for the agent loop).

---

## 3. Sessions + Modes

**Key insight:** There is no architectural difference between "interactive mode" and "autonomous mode." It's the same agent driver, same tools, same loop. The only difference is the **mode** (system prompt) telling the model how to behave.

### Modes (data, not code)

Modes are just markdown files with system prompts. Editable, add your own:

```
~/.llm-harness/modes/
├── assistant.md     # Interactive — waits for user, suggests, asks questions
├── agent.md         # Spec-driven — works autonomously to completion
├── reviewer.md      # Read-only — finds issues, doesn't edit
├── security.md      # Audits for vulnerabilities
├── junior-dev.md    # Asks a lot, slow, safer
└── senior-dev.md    # Confident, decisive, fast
```

### Default behaviors per mode

**`assistant`** — Interactive, conversational
- Wait for user input
- Suggest rather than act unilaterally
- Ask clarifying questions when ambiguous
- Run tools only when explicitly asked or clearly needed
- Doesn't write code unless asked

**`agent`** — Autonomous, spec-driven
- Work the assigned task to spec
- Use tools freely
- Only stop when every acceptance criterion is met, or you hit a real blocker
- Report progress via `task_log_progress` after every meaningful action
- Verify everything (run tests, lint) before declaring done
- Mark task `blocked` when user input is genuinely needed

### Control transfer = mode swap

- **Assume control:** swap mode from `agent` → `assistant`, save current state, the agent now waits for you
- **Relinquish control:** swap back to `agent`, hand it context about what you did while in control, it resumes
- This is literally a system prompt change — no state migration, no architectural switch

### Session features

- Session creation, resume, archive
- Per-session: assigned mode, model, project, current task
- Context trimming: auto-summarize + prune when approaching token limits
- Conversation log per session (separate from the task progress log)
- Multiple concurrent sessions per project

---

## 4. Projects (Multi-Repo Workspaces)

✅ **Repo strategy:** Multi-repo / polyrepo projects. Single-repo projects just have one repo in the list.

### Concept

A Project = a workspace with one or more git repos, project-level settings, scoped vault credentials, and a task namespace.

### Project schema

```yaml
id: my-cool-app
name: "My Cool App"
workspace:
  root: ~/work/my-cool-app
  repos:
    - path: web/
      remote: [email protected]:myorg/web.git
      branch: main
      role: frontend
    - path: api/
      remote: [email protected]:myorg/api.git
      branch: main
      role: backend
    - path: shared-types/
      remote: [email protected]:myorg/shared-types.git
      branch: main
      role: library
settings:
  default_model: claude-sonnet-4
  agent_model: claude-sonnet-4
  cheap_model: gpt-4o-mini
  commands:
    test: "pnpm test"
    lint: "pnpm lint"
    build: "pnpm build"
    format: "pnpm format"
    install: "pnpm install"
    typecheck: "pnpm typecheck"
  ignored_paths:
    - node_modules
    - dist
    - .next
    - coverage
    - "*.lock"
  conventions: |
    TypeScript, Next.js 14, Tailwind, Zustand, Vitest, pnpm.
  risk_policies:
    require_approval_for: ["rm -rf", "git push --force", "DROP TABLE"]
    blocked_commands: ["sudo *", "curl * | bash", "mkfs*"]
    max_files_per_edit: 50
vault_scope:
  allowed_credentials:
    - vault://github/work
    - vault://npm/internal
  denied_credentials:
    - vault://github/personal
prompts:
  mode: senior-typescript-engineer
  extras: |
    Always run `pnpm test` after changes. Never commit .env files.
```

### Multi-repo behavior

- Each repo gets its own worktree per agent session (no collisions)
- Cross-repo search aggregates results from all repos
- `harness project test` runs each repo's test command, aggregates results
- Cross-repo PRs opened in dependency order, linked in descriptions
- Per-repo credential binding possible

### Project commands

```
harness project create <name>          # Interactive
harness project clone <github-url>     # Create + clone in one step
harness project list
harness project switch <name>
harness project info
harness project edit                   # Open project.yaml in $EDITOR
harness project detect                 # Auto-detect language/framework/build commands
harness project add-repo <github-url>  # Add another repo
harness project status                 # Git status across all repos
harness project test / lint / build    # Run project-wide
```

### Storage

```
~/.llm-harness/
├── projects/
│   ├── index.json
│   ├── my-cool-app.yaml
│   └── ...
```

---

## 5. Tasks (Persistent Work Records)

**Core principle:** A Task is a structured object in the harness database, NOT a string in the agent's context. The agent reads from and writes to a Task; it doesn't contain it. Tasks survive context compaction, session restarts, agent crashes, model swaps, mode swaps.

### Task schema

```yaml
id: P:my-cool-app/T-2026-0628-001
project: my-cool-app
title: "Add dark mode toggle to settings page"
status: in_progress            # draft | open | planned | in_progress | blocked | review | done | abandoned
priority: medium               # low | medium | high | urgent
created_at: 2026-06-28T09:14:00Z
created_by: user               # user | agent:<session_id>
assigned_to: agent:refactor-auth
parent_task: null
tags: [ui, frontend, settings]

context:
  background: |
    Users have asked for dark mode since v2. We have partial
    infra (theme tokens exist) but no toggle in the UI.
  goal: |
    Add a working dark mode toggle in Settings → Appearance
    that persists across sessions.
  acceptance_criteria:
    - "Toggle visible in /settings/appearance"
    - "Clicking switches entire UI to dark theme"
    - "Choice persists in localStorage and user profile"
    - "No FOUC on page reload"
    - "All existing components render correctly in dark"
  out_of_scope:
    - "Per-component theme customization"
    - "System-preference auto-detection (separate task)"

plan:
  approach: |
    1. Add toggle component
    2. Wire to existing theme store
    3. Update theme provider
    4. Test all primary views
  steps:
    - id: .1
      title: "Create DarkModeToggle component"
      status: done
    - id: .2
      title: "Wire toggle to theme store"
      status: done
    - id: .3
      title: "Add dark mode CSS variables"
      status: in_progress
    - id: .4
      title: "Test all components render correctly"
      status: pending

dependencies:
  blocks: []
  blocked_by: []

required_credentials:
  - vault://github/work
  - vault://npm/internal

work_session:
  session_id: agent:refactor-auth
  container_id: c-7a3f         # null if not containerized
  started_at: 2026-06-28T09:20:00Z
  paused: false

progress:
  - timestamp: 2026-06-28T09:20:14Z
    status: in_progress
    entry: "Starting work on DarkModeToggle component."
    actions_taken:
      - "read_file: src/pages/Settings.tsx"
    next_step: "Create DarkModeToggle.tsx"
  - timestamp: 2026-06-28T11:05:00Z
    status: in_progress
    entry: "User picked Option A. Continuing."
    resolution: "Applied Option A"
    next_step: "Run visual regression"
```

### Why this beats TODOs

- **Survives context compaction** — progress log is the recovery point
- **Explicit blockers** — not buried in chat
- **Handoff-safe** — different agent/session can pick up seamlessly by reading the log
- **Verifiable done** — can't mark `done` without acceptance criteria checked off with evidence
- **Inspectable by you** — read progress without scrolling through 200 messages

### Anti-abandonment mechanisms

1. **Progress log checkpointing** — agent must call `task_log_progress` after every meaningful action
2. **Stalled-task detection** — task is `in_progress` but no log entry for N hours → flag as `stalled`
3. **Auto-summarize on compaction** — context is summarized into the progress log *before* trimming
4. **Handoff protocol** — on session restart, agent reads progress log first, picks up from last step
5. **Acceptance criteria gates** — `done` requires every criterion verified with evidence

### Task creation flows

1. **Manual** — fill out a structured form in the console
2. **Co-creation** — describe it in chat, agent drafts a Task, you review/edit/approve
3. **Auto-generated** — agent creates Tasks from a higher-level intent (e.g., "fix all failing tests" → one task per failure)
4. **From chat history** — "make a task out of what we just discussed" → agent drafts from conversation

### Agent tools for tasks

```json
{ "name": "task_create" }
{ "name": "task_update" }
{ "name": "task_get" }
{ "name": "task_list" }
{ "name": "task_log_progress" }
{ "name": "task_break_down" }
{ "name": "task_assign" }
```

### Storage

```
~/.llm-harness/tasks/<project-id>/<task-id>.yaml
```

YAML so it's greppable, hand-editable, optionally version-controllable.

---

## 6. Tool Integrations

What the agent can actually do to your codebase.

### Core tools

- **File ops:** read, write, edit (partial), move, delete, glob
- **Shell:** run commands, capture stdout/stderr, stream output, set timeout
- **Git:** diff, status, log, branch, commit, push, fetch
- **Search:** grep, find, semantic search (optional, needs indexer)
- **Test runner:** run project test command, parse results, report back
- **Linter / typechecker:** run project's lint/typecheck commands

### Codebase awareness

- **Tree-sitter index** — parse-aware code reading (functions, classes, imports)
- **Embeddings-based semantic search** — "find code that does X"
- **Project conventions ingestion** — at session start, prime the agent with the project's conventions from `project.yaml`

### IDE-like hooks (future)

- LSP integration: go-to-definition, find references, type hints
- Debugger integration: step through, inspect variables

---

## 7. Credential Vault (Flexible)

**Core principle:** The agent knows *that* it has credentials and *what they're for*, but never knows *what they are*. Secrets are stored encrypted, accessed via opaque references, used via injection templates.

### Storage

- Encrypted at rest using OS keychain (macOS Keychain, Linux `secret-service`, Windows Credential Manager)
- Fallback: `~/.llm-harness/vault.enc` with passphrase-derived key
- Each credential is just a named secret — no type enum

```json
{
  "id": "github/work",
  "created_at": "...",
  "encrypted_value": "...",
  "nonce": "..."
}
```

### Injection templates (the flexibility)

Templates are declarative JSON saying "when the agent asks to use credential X, here's how to expose it." Editable from the console — no code change to support a new tool.

```json
{
  "credential": "jira/work",
  "templates": [
    {
      "name": "jira_cli_env",
      "description": "Inject as env vars for jira-cli",
      "injection": {
        "env": {
          "JIRA_API_TOKEN": "$value",
          "JIRA_USER": "[email protected]",
          "JIRA_INSTANCE": "company.atlassian.net"
        }
      }
    },
    {
      "name": "jira_curl_header",
      "injection": {
        "command_wrapper": "curl -H 'Authorization: Bearer $value' {original_args}"
      }
    }
  ]
}
```

### Supported injection modes

- **`env`** — inject as environment variable, scrubbed from logs
- **`command_wrapper`** — wrap the command with auth bits
- **`file`** — write to temp file (mode 600), mount path, delete after
- **`ssh_key_path`** — path to an SSH key for SSH-based auth
- **`stdin`** — pipe value to a command's stdin
- **`plugin://`** — custom user-defined injection

### Agent API

```json
{
  "name": "vault_use",
  "parameters": {
    "credential": "vault://jira/work",
    "template": "jira_cli_env",
    "command": "jira issue list --project DEV",
    "cwd": "/repo",
    "timeout_s": 30
  }
}
```

For containers, a `vault_request` variant routes through the host daemon.

### Starter template library (all editable)

- `gh_cli_env`, `ssh_agent_forward`
- `gitlab_cli_env`
- `jira_cli_env`, `linear_cli_env`
- `npm_publish_env`, `pypi_publish_env`
- `docker_registry_env`
- `aws_env`, `gcp_env`
- `tavily_env`
- `openai_env`, `anthropic_env`
- `curl_bearer`, `curl_basic_auth` (generic)

Add a new tool? Pick a generic template or write a new template JSON. Zero code.

### Policies per credential

- **Scope paths** — only usable in certain directories (`~/work/*`)
- **Rate limits** — max N uses per hour/day
- **Require approval** — certain templates need user approval
- **Per-project binding** — only available in certain projects

### Audit log

Append-only log of every credential use:
```
2026-06-30 11:02:14 | jira/work     | jira_cli_env  | cmd: `jira issue list`     | agent:refactor-auth | ✓ 1.2s
2026-06-30 11:02:18 | tavily/search | tavily_env    | cmd: `python search.py`    | agent:refactor-auth | ✓ 3.4s
```

Records which template and which command. Never the secret value. Exportable as JSON/CSV.

### Storage

```
~/.llm-harness/
├── vault.enc
├── vault.key                  # From OS keychain
└── vault.log                  # Append-only audit log
```

---

## 8. Containerized Isolated Agents

✅ **Runtime:** The `ContainerRuntime` interface is **fully designed and configured for all major runtimes** (Podman, Docker, Apple Containerization, nerdctl, etc.) — but **only Podman is implemented in v1**. Users can pick any runtime in settings; if it's not Podman, the system tells them clearly which runtimes are supported right now and which are planned. Adding a new runtime is a self-contained implementation of the interface, no orchestrator changes needed.

### What happens when an agent spawns in a container

1. **Pull the repo(s)** — configurable depth / branch (uses project's worktrees)
2. **Install dependencies** — auto-detect via lockfile (`package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`)
3. **Baseline tests** — run project's test command, confirm green starting state
4. **Agent loop runs** — full tool access inside the sandbox, communicating via the standard driver interface (see Section 11)
5. **Verification** — run full test suite + linter as final check
6. **PR submission** — push branch, open PR via vault credentials, capture URL
7. **Cleanup** — auto-remove container, or keep for inspection (`harness keep`)

### Sandbox policies

- **Default-deny network egress** — allowlist: package registries, vault daemon, gh/GitHub API, LLM providers
- **Resource caps** — per-container CPU, RAM, disk quotas (so one runaway agent doesn't kill your machine)
- **Filesystem isolation** — only the project's worktrees + necessary mounts visible
- **Vault access only via host daemon** — container has no copy of secrets on disk

### Image strategy

- Default base image per language stack (Node, Python, Rust, Go, etc.)
- User can pre-bake custom images with their toolchain
- Layer caching for fast restarts
- All images OCI-compliant (works with both Docker and Podman)

### Lifecycle states

```
Created → Running → Paused → Verifying → PR-Ready → Done
                                    ↓
                                  Failed / Abandoned
```

### Auth for push / PR

- **Host creds (preferred):** mount host's `~/.ssh` (read-only) and/or `~/.config/gh` into the container
- **Vault creds:** container calls `vault_request` against host daemon over a unix socket or HTTP with mTLS
- **No raw secrets on container disk** — vault calls happen via socket, secrets stay on host

### Abstraction layer (config supports all, v1 ships Podman only)

```python
class ContainerRuntime:
    def build(image_spec: str) -> Image
    def run(image: Image, config: ContainerConfig) -> Container
    def exec(container: Container, cmd: list) -> Result
    def stop(container: Container) -> None
    def logs(container: Container) -> Stream
    def stats(container: Container) -> Stats

# Runtime implementations:
# - PodmanRuntime          (v1 — implemented and supported)
# - DockerRuntime          (planned, easy to add — same OCI primitives)
# - AppleContainerRuntime  (planned, macOS only)
# - nerdctlRuntime         (planned)
# - CRIDockerRuntime       (planned, via CRI-O / containerd)
```

### Settings UX

```
┌─ Settings → Container Runtime ─────────────────────────────────┐
│                                                                  │
│  Runtime: [ Podman         ▼ ]                                   │
│           ├─ ● Podman             (v1, fully supported)         │
│           ├─ ○ Docker             (planned)                     │
│           ├─ ○ Apple Container   (planned, macOS only)         │
│           └─ ○ nerdctl           (planned)                     │
│                                                                  │
│  Podman socket: [/run/podman/podman.sock____________] [Detect]  │
│  Resource defaults:                                             │
│    CPU:    [2 cores  ▼]    RAM: [4 GB ▼]    Disk: [10 GB ▼]    │
│  Default base image strategy: [ per-language ▼ ]                │
│                                                                  │
│  [ Test connection ]   [ Save ]                                 │
└──────────────────────────────────────────────────────────────────┘
```

If user picks a runtime that isn't implemented yet, the UI shows a clear message: *"Docker support is planned but not yet shipped in v1. The interface is ready — implementation tracked. For now, please use Podman."* No silent failure, no broken state.

---

## 9. Concurrent Agent Cockpit (the canonical management surface)

**What it does:** The **cockpit is the canonical way to manage everything** — multiple agents, projects, tasks, vault, settings. It's not just a view onto agents, it's the control plane for the whole orchestrator. If you can do something in the orchestrator, you do it from the cockpit.

**Two UI surfaces, same data, different ergonomics:**
- **Web GUI (primary, most useful)** — visual, mobile-friendly, rich rendering. Best when you have a real screen and want to see multiple agents, diffs, code side-by-side.
- **TUI** — keyboard-driven, fast, runs over SSH. Handles both multi-agent overview AND single-agent focus in the same interface — press a key to zoom into one agent, press another to zoom back out. No separate "single-agent mode."

**Relationship:**
- Both backed by the same event stream from the driver interface
- Both can do everything — launch agents, switch modes, manage tasks, edit vault, change settings
- The `harness` CLI exposes subcommands (`harness project ...`, `harness vault ...`, etc.) for scripting and CI — these are operators, not a separate UI surface

**Why two surfaces, not one:** GUI is best for visual/spatial reasoning (multiple agents, diffs, code). TUI is best for keyboard-driven power use and SSH workflows. Both share the same backend; switching is just a different rendering.

### Cockpit features (multi-agent management)

- **Agent list panel** — all active agents with status (`running`, `blocked`, `idle`, `error`)
- **Live activity feed** — see what each agent is doing right now: current file, current command, last reasoning step
- **Quick switch** — one keystroke to jump into any agent's full view
- **Per-agent chat** — talk to individual agents while others keep working
- **Broadcast** — send a message to multiple agents at once, pause/resume all in lockstep
- **Resource monitor** — CPU, RAM, network per agent
- **Cost tracker** — tokens spent per agent in real time
- **Priority / scheduling** — mark which agent should get more compute
- **Shared scratchpad** — agents can leave notes for each other ("I edited `auth.py`, check before merging")
- **Result aggregation** — unified diff / summary across all agents' work
- **Conflict detection** — flag when two agents edit the same file; offer merge or pick-one
- **Project / task / vault management** — full admin of all orchestrator state lives in the cockpit
- **Settings** — global config, runtime selection, profiles

### Single-agent focus in the TUI

The TUI handles both multi-agent and single-agent modes through the same interface — just at different zoom levels. From the multi-agent view, press `Enter` or `f` to focus on one agent and see its full event stream. Press `Esc` to zoom back out. No separate "CLI mode" — the TUI is the single-agent view when you want it, and the multi-agent view when you want that.

### CLI subcommands (not a UI surface)

The `harness` CLI exposes subcommands for scripting and CI:
- `harness project ...`
- `harness task ...`
- `harness vault ...`
- `harness agent spawn/start/stop ...`
- `harness cockpit` — launches the TUI cockpit

These are operators, not UI surfaces. They use the same orchestrator internals but output text to stdout / read from stdin.

### UI surfaces

- **Web cockpit (GUI) — v1 primary, most useful** — visual multi-agent management, mobile-friendly, handles rich rendering of diffs/code well. Best when you have a real screen and want to see everything at once.
- **TUI cockpit — v1** — keyboard-driven, fast, runs over SSH, lightweight. Handles both multi-agent management AND single-agent focus — no separate CLI needed. Press a key to focus on one agent, press another to see all. Same interface, different zoom level.
- All backed by the same event stream from the orchestrator.

No standalone CLI / single-agent view — the TUI does both jobs, and the CLI commands (`harness project`, `harness vault`, `harness task`) are subcommands for scripting and CI, not a separate UI surface.

### Cockpit display

```
┌─ Cockpit ───────────────────────────────────────────────────────┐
│                                                                  │
│  ● agent-auth    [Container A]    running    12m                 │
│    └─ Currently: edit_file src/auth.py (line 47)                │
│    └─ Task: T-001 Dark mode toggle                               │
│                                                                  │
│  ● agent-bugbot  [Container B]    blocked    4m                 │
│    └─ Asks: "Add test for empty input — should it return 400?"  │
│    └─ [ Answer ]  [ Suggest options ]                            │
│                                                                  │
│  ● agent-cleaner [Local process]  running    8m                 │
│    └─ Currently: shell `pnpm test` (streaming)                  │
│                                                                  │
│  Press: [1] focus agent-auth  [2] focus agent-bugbot            │
│         [a] assume control  [b] broadcast  [p] pause all        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. Configuration & Settings

### Per-project settings

- Default model, agent model, cheap model
- Build / test / lint / format commands
- Ignored paths
- Conventions (free-form notes for the AI)
- Risk policies (require-approval list, blocked commands, max files per edit)
- Vault credential scope (allowed / denied)
- Default mode + mode-specific extras

### Global settings

- Default provider
- Default models for different roles
- Vault settings (keychain integration)
- Container runtime (Podman, etc.)
- Default base images per language
- Theme, keybindings, UI preferences
- Notifications (when to ping you)

### Profiles (future)

- "Work" vs "personal" vs "client X" — different providers, vault creds, models, prompts
- Switch profiles cleanly

---

## 11. Agent Driver Interface (the key abstraction)

**Core principle:** Every agent — local subprocess, containerized, remote — exposes the same interface. The orchestrator doesn't care how the agent is implemented underneath.

### Why this matters

This is what lets us:
1. Use OpenCode via Go SDK initially (no subprocess needed)
2. Write our own thin driver later (or now)
3. Run agents in containers, locally, or on remote machines interchangeably
4. Swap any piece without touching the orchestrator

### Architecture

```
┌─ Your laptop ─────────────────────────────────────────────┐
│                                                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Orchestrator (your code)                           │  │
│  │  - Cockpit UI (Web primary, TUI for keyboard)      │  │
│  │  - Talks to drivers via the standard interface     │  │
│  │  - Manages N drivers concurrently                  │  │
│  └──────┬───────────────────────────────────────────┬─┘  │
│         │ in-proc pipe  │ HTTP/WS to container A  │     │
│         │               │ HTTP/WS to container B  │     │
└─────────┼───────────────┼──────────────────────────┼─────┘
          ▼               ▼                          ▼
   ┌─────────────┐ ┌─────────────┐           ┌─────────────┐
   │ Local       │ │ Container   │           │ Container   │
   │ Driver      │ │ A Driver    │           │ B Driver    │
   │ (subprocess)│ │ (port 7001) │           │ (port 7002) │
   └─────────────┘ └─────────────┘           └─────────────┘
```

### Standard driver interface

```yaml
endpoints:
  POST /message:
    purpose: Send a message to the agent
    input: { role: "user", content: "..." }
    output: { accepted: true, queued_at: timestamp }

  WS /events:
    purpose: Stream of structured events from the agent
    events:
      - type: "thinking"
      - type: "tool_call"
      - type: "tool_result"
      - type: "message"
      - type: "blocker"
      - type: "progress"
      - type: "state_change"

  GET /state:
    purpose: Current snapshot of the agent
    output:
      state: "running" | "blocked" | "idle" | "error"
      current_task: "T-..."
      last_action: "..."
      tokens_used: 12453
      uptime_s: 847

  POST /control:
    purpose: Control commands
    commands: ["pause", "resume", "abort", "compact_context"]

  POST /assume:
    purpose: Take control from the agent
    effect:
      - Pauses the agent
      - Returns: { shell_url: "ws://...", workspace_path: "/repo" }
      - You get a shell + file editor in the agent's workspace
      - On relinquish, agent resumes from checkpoint with context of what you did
```

### Take-over flow

1. You press `a` or click "Take over"
2. Orchestrator sends `POST /assume` to the driver
3. Driver pauses the agent, returns a shell URL + workspace path
4. Cockpit shows a terminal pane into the workspace
5. You run commands, edit files — all in the agent's environment
6. You click "Relinquish"
7. Driver resumes the agent, telling it what you did
8. Agent continues with that context

### Driver implementations (planned)

- **`OpenCodeDriver`** — uses the official Go SDK (`github.com/sst/opencode-sdk-go`). v1 default.
- **`LocalDriver`** — our own thin agent loop, no external dep. v1 or v2.
- **`ContainerDriver`** — runs in a container, listens on a port.
- **`RemoteDriver`** — runs on another machine, listens on a network port.

---

## 12. Architecture Decision: Embed-then-Own

✅ **Strategy:** Adapter pattern with a swap path.

- **v1:** Build orchestrator + OpenCode driver using the official Go SDK (`github.com/sst/opencode-sdk-go`). No subprocess wrapping needed — direct Go-to-Go integration.
- **Soon (if needed):** Write our own thin driver. The agent loop itself isn't that much code (a few hundred lines).
- **Later:** Add fancy stuff (better providers, custom tools) without touching the orchestrator.

The agent loop we need to write ourselves is maybe a few hundred lines:
- Send messages → LLM
- Parse response (text + tool calls)
- Execute tool calls
- Stream results back
- Loop until done

The hard part isn't the loop — it's providers, terminal UI, tools, and everything around it. By using OpenCode first, we skip the boring parts and focus on what makes this orchestrator unique (multi-agent orchestration, vault, tasks, projects, cockpit).

**OpenCode is the safest bet** — SST-backed, MIT licensed, ~158k stars, mature codebase, native Go SDK. But the adapter interface means we can swap to a custom driver (or even Pi/OpenClaw via HTTP later) without rewriting the orchestrator.

---

## 13. Extensibility / Plugin System

### Plugin types

- **Custom tools** — define a tool in config, AI can call it
- **Modes** — drop a markdown file into `modes/`, instantly available
- **Credential templates** — drop a JSON into the vault config, instantly available
- **Task templates** — pre-filled task structures for common work
- **Container base images** — define custom base images per project

### Hooks

- Run scripts before/after AI actions
- Pre-commit hooks per project
- Post-PR-creation notifications

---

## 14. What v1 Ships With (initial scope)

### Must have (v1)

- ✅ Provider abstraction (OpenAI-compatible, Ollama, MiniMax, GLM, Anthropic)
- ✅ Session + mode model
- ✅ Project workspaces (multi-repo)
- ✅ Task system with progress logs
- ✅ Tool integrations (file, shell, git)
- ✅ Credential vault with injection templates
- ✅ Containerized agents (Podman)
- ✅ Concurrent agent cockpit (Web primary, TUI handles multi + single agent views)
- ✅ Agent driver interface + OpenCode driver (via Go SDK)
- ✅ Configuration & settings

### Nice to have (v1.5 / v2)

- Web-based cockpit
- Embeddings-based semantic search
- Tree-sitter codebase indexing
- Per-repo vault credential binding
- Cross-repo PR orchestration
- Notification system (desktop, terminal bell)
- LSP integration
- Cost management (budgets, alerts)
- Observability / session replay

### Parked (later)

- Cloud sync / remote backup (online) ✅ parked
- Multi-user / shared sessions
- Mobile app
- IDE plugin (VSCode/JetBrains)
- Cloud-hosted version of the platform
- WASM-based agent sandboxes
- Firecracker microVMs for higher security
- Kubernetes orchestration for many agents across many machines

---

## 15. Project Structure (proposed)

```
orchestrator/                        # Go module
├── go.mod
├── go.sum
├── cmd/
│   └── harness/                      # Main CLI entry point
│       └── main.go
├── internal/
│   ├── drivers/                      # Agent driver implementations
│   │   ├── driver.go                # AgentDriver interface
│   │   ├── opencode.go              # OpenCode via Go SDK (v1)
│   │   ├── local.go                 # Our own thin driver (later)
│   │   └── container.go             # In-container driver (later)
│   ├── providers/                   # LLM provider abstractions (used by local driver)
│   │   ├── provider.go              # Provider interface
│   │   ├── openai_compat.go         # OpenAI-compatible
│   │   ├── ollama.go
│   │   ├── minimax.go
│   │   ├── glm.go
│   │   └── anthropic.go
│   ├── session/                     # Session state, mode management
│   ├── project/                     # Project workspaces, repo binding
│   ├── task/                        # Task system + progress logs
│   ├── vault/                       # Credential storage + injection
│   │   ├── vault.go                 # Encrypted storage
│   │   ├── template.go              # Injection template engine
│   │   └── inject.go                # Secret injection (env/file/stdin/wrapper)
│   ├── container/                   # Container runtime abstraction
│   │   ├── runtime.go               # ContainerRuntime interface
│   │   ├── podman.go                # Podman implementation (v1)
│   │   └── docker.go                # Future
│   ├── cockpit/                     # Concurrent agent UI (canonical management surface)
│   │   ├── web/                     # Web UI (primary, most useful) — SvelteKit or stdlib + HTMX
│   │   └── tui/                     # TUI cockpit (multi-agent + single-agent focus) — Bubble Tea
│   ├── tools/                       # File, shell, git, search
│   ├── mode/                        # Mode loader (markdown)
│   ├── config/                      # Settings
│   └── plugin/                      # Plugin loader
├── modes/                           # Default mode markdown files
│   ├── assistant.md
│   ├── agent.md
│   ├── reviewer.md
│   └── ...
├── docs/
└── README.md
```

**Dependency strategy:**
- `github.com/sst/opencode-sdk-go` — OpenCode driver (v1)
- `github.com/spf13/cobra` — CLI framework
- `github.com/charmbracelet/bubbletea` — TUI cockpit (later)
- `github.com/containers/podman/v5` or shelling to `podman` CLI — container runtime
- Standard library for crypto, HTTP, file I/O — no need for heavy frameworks
- Web cockpit: either stdlib `net/http` with HTMX for simplicity, or SvelteKit if you want a real SPA later

---

## 16. Open Questions

⚠️ Final name TBD. Candidates being considered:
- Forge
- Conductor
- Workbench / Bench
- Atelier
- Helm
- Director
- Studio

⚠️ ~~UI direction for cockpit~~ **Resolved:** Two surfaces — **Web GUI (primary, most useful)** for visual multi-agent management, **TUI** for keyboard-driven multi-agent + single-agent focus (zoom in/out in the same interface). No separate CLI UI — `harness` subcommands are operators for scripting/CI.

✅ **Driver for v1:** **OpenCode** (by SST/Anomaly) via the official Go SDK (`github.com/sst/opencode-sdk-go`). Justification:
- **Native Go SDK** — generated with Stainless, type-safe, direct `import` from our Go orchestrator. No subprocess, no HTTP bridge.
- **Go source** — same language as our orchestrator, we can read it for reference / fork if needed
- **Headless HTTP server** (`opencode serve`) with OpenAPI spec — fallback integration path
- **75+ providers** including MiniMax, OpenAI, Anthropic, Ollama, OpenRouter
- **Built-in features** we'd otherwise build: LSP, MCP, multi-agent (build/plan/debug), file ops, shell, git, plugins
- **Already proven in orchestrators** — Nango used it for 200+ API integrations
- **Tool injection** via plugins (config, not code)
- **Mode swap** via system prompt customization (build vs plan agents)
- **You already use it** — zero context switching

Why not Pi (revised): Pi's SDK is TypeScript-only. With Go orchestrator, we'd bridge to it via subprocess or HTTP — extra complexity for no gain. Pi's minimalism is great when you're starting from scratch in TS, but with Go orchestrator + OpenCode's Go SDK, the calculus flips.

When we write our own thin driver later, it goes behind the same `AgentDriver` interface — orchestrator code doesn't change.

⚠️ Whether to ship our own thin driver alongside OpenCode in v1.2, or wait until OpenCode gets annoying. Lean toward waiting — OpenCode is mature, well-maintained, and the Go SDK is stable. Our driver adds the most value via the orchestrator layer (multi-agent, vault, tasks, projects) rather than replacing the agent loop.

⚠️ Vault unlock UX — when do you unlock the vault? Per session, per project, or once at startup?

---

## 17. Locked Decisions Summary

| Decision | Choice |
|---|---|
| Repo strategy for Projects | Multi-repo (Strategy 3) — single-repo is just one repo in the list |
| Storage | Local only — `~/.llm-harness/`, no cloud sync in v1 |
| Container runtime | `ContainerRuntime` interface configured for all (Podman, Docker, Apple, nerdctl); **only Podman implemented in v1** — others clearly marked as planned |
| Driver strategy | **OpenCode via Go SDK** in v1; write our own thin driver later behind the same interface |
| Mode architecture | Single agent driver + mode system prompts (assistant / agent / reviewer / etc. — same driver, different system prompt) |
| UI surfaces | **Web GUI (primary, most useful) + TUI (handles both multi-agent cockpit AND single-agent focus via zoom).** No separate CLI UI — `harness` subcommands are operators, not a UI surface. |
| Online sync | Parked for future |
| Language | **Go** — single binary distribution, native OpenCode SDK integration, mature ecosystem for CLI/network/containers, different from Python/TS as a learning experience |
| Driver | **OpenCode via Go SDK** (`github.com/sst/opencode-sdk-go`) |
| Cloud-hosted version | Parked |
| Multi-user | Parked (single user for now) |

---

*End of high-level plan. Breakdown into implementation tasks not started — user will signal when ready.*