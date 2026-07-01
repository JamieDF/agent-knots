> **Note:** Captured under the prior project name "harness"; see CHANGELOG for the rename.

# ADR 0001: Embed-then-Own for the agent driver

**Status:** Accepted
**Date:** 2026-06-30

## Context

agentjam needs to drive an AI coding agent. The orchestrator is the
interesting part (multi-agent, vault, tasks, projects) — the agent loop
itself is well-trodden ground. We need to choose how to integrate an
agent engine.

## Options considered

1. **Build from scratch.** Own every line. Maximum control. Months of
   work to reach parity with existing tools.
2. **Wrap an external CLI as a subprocess.** Use Pi, OpenCode, Claude
   Code, etc. via stdin/stdout. Fast to ship, but IPC is fragile and
   you inherit the wrapped tool's bugs and API churn.
3. **Embed via library.** Use a Go-native library that exposes an
   SDK. Tighter integration than subprocess, more flexibility than
   wrapping. Requires the upstream library to be Go.
4. **Adopt a wrapper framework.** Use something like LangChain or
   eino. Heavy, opinionated, brings its own conventions.

## Decision

We chose **option 3**: embed a Go-native SDK. Specifically,
[OpenCode's Go SDK](https://github.com/sst/opencode-sdk-go).

Reasons:

- **Native Go integration.** No subprocess, no IPC bridge, no type
  translation. The orchestrator imports the SDK directly.
- **Single language.** Same Go codebase for orchestrator + agent
  engine. Easier refactoring, shared types, shared tests.
- **Mature upstream.** OpenCode is SST-backed, MIT-licensed, ~158k
  stars on GitHub.
- **Already proven in orchestrators.** [Nango used OpenCode for
  200+ API integrations](https://nango.dev/blog/learned-building-200-api-integrations-with-opencode/).
- **Multi-provider.** OpenCode supports 75+ providers including the
  ones we care about (OpenAI, Anthropic, MiniMax, GLM, Ollama).

## Embed-then-Own

We adopt the "embed-then-own" pattern:

- **v1:** Use the OpenCode SDK directly.
- **v2 (if needed):** Write our own thin driver when OpenCode gets
  annoying, behind the same `AgentDriver` interface.

The interface (`internal/agent/driver.Driver`) is the contract. The
implementation is replaceable. The orchestrator code doesn't change.

## Why not Pi?

Pi's SDK is TypeScript-only. With Go orchestrator, we'd bridge to Pi
via subprocess or HTTP — extra complexity for no gain over OpenCode.
Pi's minimalism is great when starting in TS, but with Go + OpenCode's
Go SDK, the calculus flips.

## Consequences

Positive:
- Faster time-to-first-agent.
- Single-language build.
- No subprocess management in the orchestrator.

Negative:
- Coupled to OpenCode's API surface.
- When we want features OpenCode doesn't support, we either wait for
  upstream or write a parallel driver.

Mitigations:
- The `AgentDriver` interface is narrow and stable.
- A custom driver is ~few hundred lines of Go (the agent loop).
- The interface can be reimplemented without touching the orchestrator.