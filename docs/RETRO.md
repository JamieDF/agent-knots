# Retrospective — where harness actually is vs the spec

**Date:** 2026-06-30
**Codebase:** ~12K LOC Go, 8 commits, ~3.7K LOC tests, ~32 tests passing
**Goal:** honest self-audit before going further

## TL;DR

We have a solid foundation with clean interfaces, file-backed implementations,
and good test coverage at the unit level. The hard parts — real agent execution,
real container isolation, the multi-agent cockpit in users' hands — have never
been exercised end-to-end. **The next month is about closing that gap, not
building more scaffolding.**

---

## Scorecard against the high-level plan (§14 — what v1 ships with)

| Capability | Plan says | Built | Gap |
|---|---|---|---|
| **Modes** (system prompts) | 6 default modes, user-editable | ✅ 11 mode files (assistant, agent, reviewer, security, junior-dev, senior-dev, planner, debugger, documenter, refactorer, test-writer) | — |
| **Multi-repo projects** | YAML, repos + workspace_root | ✅ `Project` struct + filestore | No validation that `workspace_root` exists at session start |
| **Tasks w/ progress log** | Persistent structured objects | ✅ `Task` + `Store` + filestore | `Mutate` interface declared but unused; no atomic multi-step mutations |
| **Vault + injection templates** | AES-256-GCM, agent can never see raw values | ✅ `vault/filestore` (~1.7K LOC) | Most injection templates shipped as examples, not auto-installed |
| **Container isolation** | Hardened podman by default | ✅ `IsolationProfile` + podman flag wiring | **Not actually run against podman yet** |
| **Session init 6-phase flow** | Resolve → Decide → Prepare → Start → Register → Prompt | ✅ | **No git-worktree integration** (creates empty dir); no egress filter |
| **TUI cockpit** | Bubble Tea, multi-agent | 🟡 Scaffold | View models wired to stub `DriverRegistry`. `Assume`/`relinquish` is a comment, not an action |
| **Web cockpit** | Primary, browser-accessible | ❌ Not built | Roadmap v0.4 |
| **Provider abstraction** | OpenAI, Anthropic, Ollama, etc. | 🟡 Indirectly via OpenCode SDK (per ADR-001) | We rely on OpenCode for everything; if it changes shape, we're coupled |
| **Driver interface** | Pluggable, mode swap = control transfer | ✅ `driver.Driver` + OpenCode impl | `Pause` maps to `Session.Abort` (destructive) — wrong semantics |
| **Take-over flow** | Mode swap = assume/relinquish | ❌ Not implemented | — |
| **Inter-session message bus** | Multiple concurrent sessions | ❌ No bus | Sessions are isolated records |
| **Plugin system** | User-defined extensions | 🟡 Plugin interface in vault only | No general plugin bus |
| **Audit log** | Every credential use logged | ✅ `vault.AuditEntry` + filestore | Network/capability denials in container not logged |

---

## What's actually solid

1. **Interfaces are clean.** `driver.Driver`, `vault.Vault`, `task.Store`,
   `project.Store`, `container.Runtime` — narrow, well-documented, sentinel
   errors via `errs.Wrap`. Adding a second implementation later won't require
   rewriting call sites.

2. **Vault is the most complete thing in the codebase.** 1.7K LOC, AES-256-GCM,
   argon2id KDF, scrubber, injection templates, audit log, plugin escape hatch.
   This is the hardest security-critical piece and it's actually right.

3. **Container isolation profile matches industry best practice and goes beyond
   defaults.** Read-only rootfs, dropped caps, no-new-privileges, seccomp,
   private netns, cgroup caps, denylist egress — checks every OpenHands misses.

4. **Test ratio is healthy in the packages that exist.** 3.7K test LOC vs
   11.8K src LOC across `internal/` ≈ 31% — not amazing for a fintech app but
   solid for an orchestrator. Where it matters (vault crypto, isolation
   profile, session init phases), coverage is real.

5. **Documentation is current.** `CHANGELOG.md` matches the git history.
   ADRs are dated and reference real design choices. `roadmap.md` is honest
   about what's not built.

---

## What's hollow (looks built, isn't)

### 1. Sessions don't have an event-stream API

`session.Session` records have no live `Events()` channel. `sessionStartCmd`
in `cmd/harness/session.go` doesn't store a handle to the live driver. The
CLI's `streamEvents()` is a heartbeat loop that returns after 1 second.

The work in `opencode.forwardEvents` exists — it streams from
`client.Event.ListStreaming` into the driver.events channel — but the
session record can't reach it. To attach to a running session you'd need a
process-locator + WS or shared file descriptor.

**Concretely:** I cannot run `harness session start --detach` in one
terminal and `harness session logs <id>` in another and see events. The
detach path returns and the events are unreachable.

### 2. `session stop` doesn't stop anything

```go
// sessionStopCmd: just sets Status=stopped, says "Note: actual driver stop
// is delegated to the container/local runtimes via session registry in a
// future cycle."
```

That's a TODO wearing a comment. The runtime's `Cleanup()` method exists
and works (I tested it via unit test pattern), but no caller invokes it.

### 3. TUI is a scaffold

`internal/cockpit/tui/tui.go` is ~750 LOC of Bubble Tea scaffolding: two
views, key bindings, a stub `DriverRegistry` interface, `mockDriver` and
`mockRegistry` test fixtures. The "assume control" action is a placeholder
comment. Nothing in the TUI actually subscribes to a real driver.

### 4. Container runtime never ran against real podman

`podman.go` emits the right flag strings (verified by
`podman_isolation_test.go`). `ContainerRuntime.Start()` calls `podman port`
and `curl` to discover the OpenCode HTTP port. **None of this has been
tested on a machine with podman installed.**

Risks:
- `podman port` output format could differ from what I assumed.
- `0.0.0.0:NNNN → 127.0.0.1:NNNN` rewrite is correct but happens after
  the container is up; if the OpenCode server inside binds to localhost only,
  we'd discover a port but the bridge wouldn't carry it.
- `--userns keep-id` requires user-namespace support enabled in the kernel.
  Hidden ubuntu/rhel false-negatives possible.
- `--storage-opt size=...` for disk quota is only supported on certain
  storage drivers. Maybe silently ignored.

### 5. No git worktrees, no real worktree branches

`ContainerRuntime.PrepareWorkspace()` does:
```go
os.MkdirAll(wt, 0o755)
return wt, nil
```

That's an empty directory. ADR-002 said per-agent worktrees at
`~/work/<project>/.harness/worktrees/<agent>/<repo>/` with branches
`agent-<id>/<repo>`. **None of that exists.** The git plumbing (clone,
checkout, branch, worktree add) needs `git` shell-outs or a Go git library;
neither is wired.

### 6. Egress allowlist doesn't actually exist

`IsolationProfile.EgressDenyList` is populated (blocks `169.254/16`, RFC1918,
cloud metadata). `IsolationProfile.EgressAllowlist` is empty. **But the
container runtime does not install any iptables rules in the container's
network namespace.** `--network private` creates the namespace; the host
filter is the only thing that does (or rather, doesn't) drop traffic.

So right now: container starts, asks for any hostname it wants, gets it.
The "deny-by-default" claim in ADR-004 is aspirational for the egress
direction.

### 7. No take-over flow

Plan §3 — "swap mode agent ↔ assistant = assume/relinquish control" — is the
key UX idea. The OpenCode driver has `SetMode()` and accepts the call but
**nothing surfaces it in any UI**. There's no `harness assume <session>`
command, no TUI binding for "press `a` to take control", nothing.

### 8. No tests cover integration

Pure unit tests. Zero `internal/integration/` test files. CI matrix in
`.github/workflows/test.yml` doesn't have an "integration" job. We have no
way to detect "the whole thing assembled together actually works."

---

## Honest assessment

| Area | Grade | Why |
|---|---|---|
| Interfaces & abstractions | A | Clean, narrow, hard to get wrong |
| Vault (security-critical) | A | Real crypto, real audit, audited-feeling |
| Project / Task storage | B+ | Works, no atomic mutations, no concurrency stress tests |
| Container isolation (spec) | B+ | Solid defaults in writing, zero real-world validation |
| Container runtime (impl) | C | Arg string tested, runtime behavior untested |
| Driver (OpenCode) | B | Type-checked against SDK, behavior untested against live server |
| Session init flow | B- | All 6 phases declared + unit tested for first 2, rest unverified |
| TUI cockpit | C | Scaffold with stub data sources |
| Web cockpit | F | Not built |
| Take-over flow | F | Not implemented |
| Cross-session coordination | F | Not designed |
| Docs & ADRs | A | Honest, dated, current |
| CI / lint / test gates | B+ | Tests run but not integration-tested, lint not run yet |

---

## Risk register (the things that'll bite us)

1. **OpenCode SDK shape may differ from my code.** All the typed
   parameters like `opencode.SessionNewParams`, `opencode.TextPartInputTypeText`,
   `SessionPromptParamsPartUnion` are real or invented — I can't tell
   without `go mod tidy` succeeding in the user's env. **First test must
   be against `opencode serve` real.**

2. **Egress filtering is the security promise we make.** Containers running
   today (in this codebase) can reach the world. That's not what ADR-004
   says. iptables rules in netns need to land before we ship v0.1.

3. **Podman on macOS.** The user is likely on macOS for development.
   Podman has a macOS path but it uses a Linux VM. Network policy and
   userns behave differently. Need to test on macOS too.

4. **GitHub API rate limits.** Agents that call `gh` a lot will hit the
   5000/hr limit. We don't have a rate-limit-aware layer.

5. **Cost.** Right now, sessions are persistent and a runaway agent can
   burn tokens. There's no per-session cost cap and no per-day kill
   switch. Both are future work and don't ship in v0.1 but should be in
   v0.2.

6. **No graceful shutdown.** Init/start paths don't install a signal
   handler. Ctrl-C in `harness session start --detach` would orphan the
   container.

---

## Recommended next-30-days plan

**Week 1 — make it actually work:**
- Real git worktree integration (clone, branch, worktree add per session)
- Egress filter via iptables in container netns (or use podman firewalld)
- Stop-driver-wiring in `session stop` (registry of live runtimes)
- Event bus for `harness session logs <id>` (SSE to local UNIX socket)

**Week 2 — make it usable:**
- Take-over flow: `harness assume <session>`, TUI binding for `a`/`r`
- Token counter / cost cap per session (driver-side; expose to UI)
- Smoke test script (`scripts/smoke.sh`) that runs an end-to-end hello-world
- macOS-on-Podman CI integration test

**Week 3 — make it presentable:**
- Web cockpit v0.4: stdlib net/http, HTMX, Pico CSS, SSE for events,
  token auth → cookie. Bind to `127.0.0.1:<port>`. ~500 LOC.
- Mobile-friendly responsive view

**Week 4 — make it safe to keep using:**
- Rate-limited GitHub API client
- Per-session cost cap (configurable per-mode)
- Integration test suite under `internal/integration/` that spins up a
  real container session against a fake LLM endpoint

**Cut from roadmap (defer):**
- Inter-session message bus
- Plugin general bus (vault-only plugin stays)
- Profiles
- Cloud sync

---

## Specific things I'd change in retrospect

1. **Don't conflate `Session.DriverID` (field) with the runtime interface's
   `DriverID()` (method).** Same name, different semantics, easy to mix up
   and it bit me once in this session.

2. **Add a `phase5`-style hook that lets phases register cleanup.**
   Right now, only the runtime's Cleanup runs on failure. If Phase 3
   succeeds (mounts set up) but Phase 4 fails, we don't always roll back
   the mount plan.

3. **Plan for the SDK dependency earlier.** `go mod tidy` worked once
   but the indirect-dep tree for the cockpit (bubble tea → lipgloss →
   muesli/ansi → …) is fragile. I should have done a one-time `go mod
   download` check at the very start.

4. **Wire the opencode forwarder into a real channel from session start,
   not just into the driver's channel.** This would have forced me to
   figure out the live-event delivery problem earlier instead of bolting
   it on now.

5. **One fewer abstraction.** I created `Runtime` interface, `LocalRuntime`,
   `ContainerRuntime`, all as separate types. The interface is sound, but
   for the first PR I'd have been better shipping both as one concrete
   struct with a `kind` field. The interface can come when there's a real
   second backend.

---

## The one-sentence version

The spec is well-shaped, the foundation is real, the integration is hollow —
**the next month is about making it run, not making it more.**

## Status: pre-launch, **not** v0.1 yet

Realistic label: **pre-alpha, foundation-complete, integration-empty.**
Tighten the 4 "F" items in the scorecard to "C" or above and we can ship
v0.1 to people who want to play with it.
