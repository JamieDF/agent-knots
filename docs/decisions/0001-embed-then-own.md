# ADR 0001: Pi via subprocess RPC as the v1 default agent backend

**Status:** Accepted (revised 2026-07-03)
**Date:** 2026-06-30 (original), 2026-07-03 (revision)

## Context

agent-knots needs to drive an AI coding agent. The orchestrator is the
interesting part (multi-agent, vault, tasks, projects) — the agent loop
itself is well-trodden ground. We need a reliable, well-tested agent
backend that integrates cleanly with our Go orchestrator.

## Decision

**Use Pi (github.com/earendil-works/pi) via its RPC mode as the v1
default agent backend.**

Pi is launched as a subprocess (`pi --mode rpc`) and communicates via
bidirectional JSONL over stdin/stdout. Our session subprocess reads
JSONL events from Pi's stdout, translates them into `driver.Event`, and
broadcasts them on the host's UNIX event socket. Control messages from
the cockpit (assume, relinquish, send) flow back through Pi's stdin as
RPC commands.

## Why Pi

1. **First-class RPC mode.** Pi ships a purpose-built headless mode
   (`--mode rpc`) with structured JSONL events, streaming deltas, and
   synchronous commands (prompt, abort, set_thinking_level, get_state,
   get_session_stats). Not an afterthought — designed for embedding.

2. **Already proven.** We use Pi via Open Design for UI mockups.
   Pi generates correct, production-quality HTML with tool calls and
   reasoning. The RPC protocol is well-documented and stable.

3. **Real token tracking.** Pi's `get_session_stats` returns actual
   input/output/cache token counts and cost. Our mock driver was
   estimating ~70 tokens/event. With Pi, we get provider-exact numbers —
   unblocking cost caps and budget alerts.

4. **Native compaction.** Pi handles context compaction automatically
   when approaching token limits. Our cockpits surface compaction events
   as progress messages so the user sees context being managed.

5. **Simple integration.** `driver.Driver` maps cleanly to Pi's RPC
   commands: Start → spawn subprocess, Send → prompt, SetMode →
   set_thinking_level + extension command, Snapshot → get_state +
   get_session_stats. No SDK dependency, no Go-to-TypeScript bridge
   complexity.

## Why not OpenCode

The original ADR chose OpenCode via its Go SDK. We wrote a 327 LOC
adapter (`internal/agent/driver/opencode/opencode.go`) but never tested
it against a live `opencode serve` instance. The SDK shape risk (typed
parameters may differ from reality) remained unvalidated. OpenCode's
Go SDK is maintained separately from the server — if either changes
shape, our driver breaks silently.

OpenCode is kept as `--driver opencode` for backward compatibility and
as a future option, but it is no longer the default.

## Architecture

```
Agent Knots session subprocess (host)
  ├── Spawns: pi --mode rpc [args]
  ├── readLoop: reads Pi stdout → translates JSONL → driver.Events
  ├── writeCmd: writes Pi stdin ← cockpit control messages
  └── Snapshot: synchronous get_state + get_session_stats
```

The `driver.Driver` interface is unchanged. Pi, OpenCode, mock, and
future backends all satisfy the same contract. The registry pattern
(`driver.Default.Build(kind, opts)`) makes adding Claude Code or a
custom agent a package import + one registration line.

## Container mode

For containerized sessions, the Pi driver runs inside a podman
container. The container mounts the worktree and extensions, and pipes
stdin/stdout to the host. Egress filtering, private network namespace,
and resource caps apply as before. The container image (`agent-knots-agent-node:20`)
is built from `containers/agent/Dockerfile` and includes Node 20 + Pi.

## Tradeoffs

- **Subprocess overhead.** Each session spawns a Node process for Pi.
  Acceptable — our session subprocess manages the lifecycle.

- **System prompt at startup only (without extension).** Without the
  agent-knots-switch Pi extension, mode swap changes only thinking level.
  With the extension (shipped in `extensions/pi-mode-swap/`), full
  persona swap is supported at runtime.

- **Pi must be installed.** `npm install -g @earendil-works/pi-coding-agent`
  or run the install script. Container mode bundles Pi in the image.

- **Local-first, no cloud dependency.** Pi calls LLM APIs directly.
  No intermediary service. API keys from environment or vault.

## Future

The registry pattern makes adding backends trivial:
- `driver.Default.Register("claude-code", ...)` — Anthropic Claude Code
- `driver.Default.Register("opencode", ...)` — already registered
- `driver.Default.Register("custom-loop", ...)` — our own agent loop

Each new backend is a package implementing `driver.Driver`. The
orchestrator, cockpits, and session lifecycle don't change.
