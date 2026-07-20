# Retrospective — where agent-knots actually is

**Last updated:** 2026-07-02
**Codebase:** ~10.9K source LOC, ~5.4K test LOC, 21 commits, 26 packages
**Goal:** honest self-audit

---

## TL;DR

All 8 "hollow items" from the initial retro are closed. The system works
end-to-end with mock drivers: session lifecycle, event streaming, TUI + web
cockpits, take-over flow, git worktrees, and egress filtering are all
functional and tested. The critical gap is the OpenCode driver — it's
written but has never run against a live `opencode serve`.

---

## Scorecard

| Capability | Status | Notes |
|---|---|---|
| **Modes** (system prompts) | ✅ | 11 mode files, loader with caching |
| **Multi-repo projects** | ✅ | YAML filestore, active-project tracking |
| **Tasks w/ progress log** | ✅ | YAML filestore, acceptance criteria gating |
| **Vault + injection** | ✅ | AES-256-GCM, argon2id, 6 injection modes, audit log. Most complete package |
| **Container isolation** | ✅ | Tested against rootless podman 5.8.2. Egress filtering via iptables |
| **Session lifecycle** | ✅ | Subprocess-based, PID tracking, clean stop (SIGTERM→SIGKILL) |
| **Event streaming** | ✅ | Bidirectional UNIX socket protocol. CLI, TUI, web all consume it |
| **TUI cockpit** | ✅ | Live multi-agent list + focus view. Assume/relinquish/pause keybindings |
| **Web cockpit** | ✅ | SSE streaming, token auth, agent list + detail, control actions |
| **Take-over flow** | ✅ | Mode swap (agent↔assistant) across CLI, TUI, web |
| **Git worktrees** | ✅ | Real worktree per session, branch management, cleanup on stop |
| **Egress filtering** | ✅ | iptables DROP for 12 CIDRs via `podman unshare nsenter` |
| **OpenCode driver** | 🟡 | 327 LOC written. Never tested against live `opencode serve` |
| **Provider abstraction** | 🟡 | Indirectly via OpenCode SDK. No direct provider support yet |
| **Integration tests** | ✅ | 10 Go tests (build-tagged) + 13-check smoke script |
| **Inter-session bus** | ❌ | Sessions are isolated. No cross-agent communication |
| **Plugin system** | 🟡 | Vault-only plugin escape hatch. No general plugin bus |

---

## What's solid

1. **Session lifecycle and IPC are real.** Detached subprocesses, event
   sockets, control channels — all tested end-to-end. Multiple UI surfaces
   (TUI, web, CLI) consume the same stream.

2. **Vault is battle-tested.** 1.7K LOC, AES-256-GCM, argon2id, scrubber,
   injection templates, audit log. The hardest security-critical piece.

3. **Cockpit works.** Both TUI and web show live agents with real-time
   event streaming. Take-over flow (assume/relinquish) works across all
   surfaces. Not a scaffold — it's functional.

4. **Container isolation is validated.** Rootless podman 5.8.2 on Linux.
   Egress filtering with real iptables rules. Worktrees with real git.

5. **Test coverage is healthy.** 5.4K test LOC (33% ratio). Integration
   tests exercise the full lifecycle. Race detector clean.

---

## What's not done yet

### Critical (blocks real usage)

1. **OpenCode driver has never run against a live server.** The 327 LOC
   adapter was written against the SDK type signatures but `go mod tidy`
   has barely worked, and no `opencode serve` integration has happened.
   The SDK shape (parameter types, event names, method signatures) may
   differ from what we coded. **This is the #1 priority.**

2. **No real agent execution.** Everything runs on mock drivers. No real
   LLM calls, no real tool execution, no real code changes. The orchestration
   layer works; the agent layer doesn't exist in practice.

### Important (quality of life)

3. **Token/cost tracking is fake.** The mock driver estimates ~70 tokens
   per event. Real token counts require a bidirectional snapshot protocol
   or driver-side accounting. No per-session cost cap.

4. **Web UI is minimal.** Functional but bare. No syntax highlighting,
   no diff rendering, no multi-agent side-by-side, no mobile optimization.
   Mockups exist for a redesign.

5. **No graceful shutdown signal handler.** Ctrl-C on `cockpit --web`
   orphans the HTTP server. Ctrl-C on `session start --detach` orphans
   the subprocess (though the subprocess catches its own signals).

6. **Pause/Resume not wired for live drivers.** `liveDriver.Pause` returns
   `ErrUnsupported`. The mock driver has no concept of pausing. Real pause
   semantics need driver cooperation.

### Nice to have

7. **No cross-agent scratchpad.** Agents can't leave notes for each other.
8. **No conflict detection.** Two agents editing the same file aren't flagged.
9. **No session replay.** Can't scrub back through past events.
10. **No LSP integration.** No code-aware reading or navigation.

---

## Risk register

1. **OpenCode SDK shape.** All typed parameters (`SessionNewParams`,
   `TextPartInputTypeText`, etc.) are real or invented — can't tell without
   running against a live server. **First priority must be a live test.**

2. **macOS Podman.** Tested on Linux only. macOS uses a Linux VM; network
   policy and userns behave differently.

3. **Cost runaway.** No per-session token cap or daily kill switch. A
   runaway real agent could burn tokens indefinitely.

4. **GitHub API rate limits.** Agents that call `gh` a lot will hit 5000/hr.
   No rate-limit-aware layer.

---

## Recommended next steps

1. **Wire up the real OpenCode driver.** Test against `opencode serve`.
   Fix SDK shape mismatches. Get one real agent running in a session.
   This unblocks everything else.

2. **Token/cost tracking.** Real token counts from the driver. Per-session
   budget. Auto-pause on budget hit. Surface in TUI + web.

3. **Web UI redesign.** Based on the mockups in `mockups/`. Better event
   rendering, status indicators, responsive layout.

4. **Graceful shutdown.** Signal handlers in cockpit + session subprocess.
   Clean port/socket cleanup.

5. **Direct provider support.** Beyond OpenCode — for cases where users
   want a different agent engine or a custom agent loop.

---

## The one-sentence version

The orchestration layer is real and tested; the agent layer (OpenCode driver)
is the critical missing piece to make agent-knots useful with real LLM agents.
