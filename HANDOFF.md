> **Note:** This document was originally authored under the prior project name "harness"; references to "agentjam" reflect the rename. See CHANGELOG.

# Handoff Context — agentjam v0.1 (pre-alpha)

> **Purpose:** this is the doc to hand to the next agent / dev that picks up
> agentjam. Read it once, top to bottom, before touching anything. Save
> yourself the two days I spent re-discovering things.

---

## 0. One-paragraph summary

`agentjam` is a **local-first Go orchestrator for multiple AI coding agents
in parallel across multi-repo projects**. v0.1 ships:

- ~12K LOC Go, 8 git commits, ~3.7K LOC tests, all tests passing
- File-backed implementations of `vault`, `task`, `project`, `mode`
- Clean `driver.Driver` interface with one impl: OpenCode via `github.com/sst/opencode-sdk-go`
- `container.Runtime` interface with `podman` impl, hardened by `container.IsolationProfile`
- A 6-phase session-init flow with local + container runtime adapters
- TUI cockpit scaffold (Bubble Tea), no web cockpit yet
- Full docs and ADRs in `docs/`

**What it can do today:** pass `go test ./internal/...`. State persists to
`~/.agentjam/`. Spawn an OpenCode session in a hardened podman container.
**What it cannot do today:** see live events from a detached session, stop a
session, take over a session, the TUI doesn't connect to real drivers, no
web GUI, no git worktrees, no egress filtering, no OpenCode SDK compilation
verified.

---

## 1. The repo, top to bottom

```
/workspace/agentjam/
├── cmd/agentjam/                  # cobra CLI, ~1700 LOC
│   ├── main.go                   # registers subcommands, version, ensure dirs
│   ├── agent.go                  # `agentjam agent spawn|list` — talks to OpenCode directly (pre-session model)
│   ├── session.go                # `agentjam session start|list|show|stop|logs` — new, runs Init flow
│   ├── project.go                # `agentjam project ...`
│   ├── task.go                   # `agentjam task ...`
│   ├── vault.go                  # `agentjam vault ...`
│   ├── cockpit.go                # `agentjam cockpit` — launches TUI
│   └── prompt.go                 # `agentjam prompt` — task→agent prompt builder
│
├── internal/
│   ├── agent/driver/             # THE interface every backend implements
│   │   ├── driver.go             # ~350 LOC of Message / Event / ToolCall / State types + Driver iface
│   │   └── opencode/             # OpenCode-backed impl, ~430 LOC
│   │
│   ├── vault/                    # credential vault (security-critical)
│   │   ├── vault.go              # interface (~600 LOC, all the types)
│   │   ├── validate.go           # credential / template validation
│   │   ├── filestore/            # AES-256-GCM, argon2id, scrubber (~1.7K LOC, THE most complete pkg)
│   │   └── plugin/               # user-defined injection plugins
│   │
│   ├── task/                     # persistent task system
│   │   ├── task.go               # Task / ProgressEntry / Store interface (~290 LOC)
│   │   └── filestore/            # YAML files
│   │
│   ├── project/                  # multi-repo workspaces
│   │   ├── project.go            # Project / Repo / Store
│   │   └── filestore/            # YAML files
│   │
│   ├── mode/                     # markdown → system prompt
│   │   └── mode.go               # Loader, parses modes/*.md
│   │
│   ├── container/                # container runtime abstraction + isolation
│   │   ├── container.go          # Runtime interface + container types
│   │   ├── isolation.go          # IsolationProfile (NEW, ~280 LOC) — hardened defaults
│   │   └── podman/               # podman CLI wrapper
│   │       ├── podman.go         # actually shells out to `podman`, ~450 LOC
│   │       └── podman_isolation_test.go  # arg-string tests (NEW)
│   │
│   ├── session/                  # session manager + init flow (NEW, ~1.7K LOC)
│   │   ├── session.go            # Manager + Session record persistence
│   │   ├── init.go               # 6-phase Init(ctx, mgr, opts) flow
│   │   ├── runtime.go            # Runtime interface (Kind, PrepareWorkspace, Start, Send, DriverID, Cleanup)
│   │   ├── runtime_local.go      # LocalRuntime
│   │   └── runtime_container.go  # ContainerRuntime (podman-backed)
│   │
│   ├── cockpit/tui/              # Bubble Tea TUI scaffold
│   │   ├── tui.go                # ~750 LOC of bubble tea, two views, stub DriverRegistry
│   │   └── styles.go             # lipgloss styles
│   │
│   ├── config/                   # ~/.agentjam/ path resolution (AGENTJAM_HOME override)
│   └── errs/                     # sentinel errors + Wrap helper
│
├── modes/                        # 11 markdown system prompts (assistant, agent, reviewer, security, junior-dev, senior-dev, planner, debugger, documenter, refactorer, test-writer)
├── examples/                     # tasks, projects, templates, sample event stream
│
├── docs/
│   ├── README.md, CHANGELOG.md, CONTRIBUTING.md
│   ├── architecture.md           # how it all fits together
│   ├── quickstart.md             # 5-min getting-started
│   ├── roadmap.md                # v0.1 → v0.5 timeline
│   ├── RETRO.md                  # honest self-audit, what's built vs hollow
│   ├── HANDOFF.md                # ← you are here
│   └── decisions/
│       ├── 0001-embed-then-own.md      # we use OpenCode SDK in v1, write own later
│       ├── 0002-vault-injection-templates.md
│       ├── 0003-... (one more)
│       └── 004-container-isolation.md  # NEW: hardened container defaults
│
├── .github/workflows/
│   ├── test.yml                  # linux/mac/windows, race + coverage
│   └── lint.yml                  # golangci-lint
│
├── Makefile, .golangci.yml, go.mod, go.sum
└── LICENSE (MIT)
```

---

## 2. The 6-phase session-init flow (newest, most important)

`internal/session/init.go::Init(ctx, mgr, opts)` walks:

```
Resolve ──► Decide ──► Prepare ──► Start ──► Register ──► Prompt
```

| Phase | Returns | On failure |
|---|---|---|
| 1. Resolve | `*Resolved` (project, task, mode, working dir, vault readiness, missing creds) | returns error, no rollback needed |
| 2. Decide | `Runtime` (LocalRuntime or ContainerRuntime) | returns error |
| 3. Prepare | `*Prepared` (working dir, mounts, env) | calls `rt.Cleanup(ctx)` |
| 4. Start | nothing (sets driver on runtime) | calls `rt.Cleanup(ctx)` |
| 5. Register | persists `*Session` to manager | calls `rt.Cleanup(ctx)` |
| 6. Prompt | sends initial prompt if task given | calls `rt.Cleanup(ctx)` |

The `Manager` is `session.New(dir)` — owns the YAML files. **The Manager
itself is NOT created inside Init**; the caller passes one in. The CLI
opens it: `mgr, _ := session.New(config.SessionsPath())`.

**`runtime_container.go::Start()`** is the meatiest phase. It:
1. Calls `hostUID, _ := container.HostUID()` (we are non-root)
2. Picks image: `--image` flag → project setting → auto-detect from
   `package.json`/`pyproject.toml`/`go.mod`/`Cargo.toml`
3. Builds `ContainerConfig` with the hardened `IsolationProfile`
4. Calls `cRuntime.Run(ctx, cfg)` → returns `podman container ID`
5. Calls `discoverPortMapping` — runs `podman port <id> 4096/tcp`, parses
   output, picks the `127.0.0.1:NNNN` line (rewrites `0.0.0.0:NNNN` if needed)
6. Calls `waitForOpenCodeReady` — `curl -sSf http://<mapping>/` every 500ms
   for up to 60s
7. Constructs an `opencode.New(...)` driver pointed at the discovered URL
8. Calls `d.Start(ctx)` to create the OpenCode session

**Notable risk in Start:** the `podman port` output format is assumed. If it
ever changes, the regex/string parsing breaks silently (returns empty
mapping → Start fails). Add a hard assertion once we can test against real
podman.

---

## 3. Architecture in 90 seconds

```
┌──────────────────────┐         ┌──────────────────────┐
│   cockpit (TUI/Web)  │ ─reads─►│   session.Manager    │
│   (operators, UI)    │         │   (YAML files in     │
└──────────┬───────────┘         │    ~/.agentjam/)      │
           │                     └──────────┬───────────┘
           │                                │
           │ writes/talks-to                │ owns
           ▼                                ▼
┌──────────────────────┐         ┌──────────────────────┐
│   Runtime            │ ─owns──►│   driver.Driver      │
│   (Local or Container│         │   (one impl:         │
│    per session)      │         │    OpenCode SDK)     │
└──────────┬───────────┘         └──────────┬───────────┘
           │                                │
           ▼                                ▼
┌──────────────────────┐         ┌──────────────────────┐
│  container.Runtime   │         │     Task / Project   │
│   (Podman today)     │         │  Vault (separate     │
│   w/ IsolationProfile│         │  processes on host)  │
└──────────────────────┘         └──────────────────────┘
```

All persistence = YAML files under `~/.agentjam/`. No database.

The vault is the **only piece the agent can never touch directly** —
agents ask via unix socket, host's vault daemon proxies commands and
scrubs responses. (Currently: vault is a Go library; the unix-socket
daemon is a v0.2 deliverable.)

---

## 4. Locked design decisions (DO NOT re-litigate)

| Decision | Rationale | ADR |
|---|---|---|
| **Language = Go** | single binary, OpenCode Go SDK, services-style orchestration | — |
| **Driver = OpenCode SDK** in v1 | mature, OSS, Has Go SDK; we keep our driver thin | ADR-001 |
| **Embed-then-own** | ship OpenCode-backed, write own thin driver later behind same iface | ADR-001 |
| **Storage = local-only** | no cloud sync in v1, just `~/.agentjam/` | high-level plan §1 |
| **Container runtime = Podman** (v1), pluggable | OpenHands-style "local + remote/cloud" model | high-level plan §8 |
| **Modes = system prompts**, not separate modes in code | same driver, different persona; control transfer is mode swap | high-level plan §3 |
| **Vault = never expose raw values**; injection templates only | credential hygiene | ADR-002 |
| **Multi-repo projects** (Strategy 3); single-repo is just one repo | the actual user pain | high-level plan §4 |
| **Web GUI (primary) + TUI** | two UI surfaces, no separate CLI UI | roadmap v0.4 |
| **Tasks = persistent structured objects** (not chat scrollback) | abandonment-resistance | high-level plan §5 |
| **Container default = non-root UID + caps dropped + read-only + seccomp + private netns + cgroup caps + cloud-metadata denied** | "I ran an agent and it didn't brick my laptop" is the explicit promise | ADR-004 |

**Things the user explicitly did NOT decide yet** (genuinely open):
- Web cockpit framework: stdlib+HTMX vs SvelteKit (I recommend stdlib+HTMX; user agrees)
- Egress filtering implementation: iptables in netns (current plan) vs eBPF (later)
- Vault daemon transport: unix socket only, or HTTP+unix (unix only is current plan)
- Take-over flow UX details (TUI binding, CLI command names)

---

## 5. Things that look done but aren't (the hollow list)

**Stop and read these — they will mislead you:**

1. **`sessionStopCmd` doesn't stop anything.** It flips the YAML record to
   `Status=stopped` and the code comment literally says "delegated to the
   container/local runtimes via session registry in a future cycle." The
   runtime's `Cleanup()` works but no caller invokes it.

2. **`streamEvents` in `cmd/agentjam/session.go` is a lie.** It's a 1-second
   heartbeat loop. There is no path from a detached session back to a
   `agentjam session logs <id>`. To fix, need: live driver registry (map of
   session-id → driver) + event-source multiplexer (likely SSE on a local
   unix socket that the daemon writes to).

3. **`ContainerRuntime.PrepareWorkspace` makes an empty dir.** No git clone,
   no worktree add, no branch creation. ADR-002 called for per-agent
   worktrees; nothing wired.

4. **`EgressDenyList` exists but nothing installs iptables rules.** So
   `--network private` namespaces the container but anything inside can
   talk to the world. ADR-004's "deny-by-default" claim is aspirational for
   the egress direction.

5. **TUI has a `mockDriver` and a `mockRegistry` for tests.** Real drivers
   are not wired. The view renders against stubs.

6. **Web cockpit doesn't exist.** Roadmap v0.4. ~2-3 days of work.

7. **`opencode.TranslateEvent` extracts the JSON type discriminator via
   re-marshaling and re-parsing** — gross but works. The OpenCode SDK's
   `EventListResponse` is a union with no clean Go discriminator; this
   is my workaround.

8. **`Pause` is broken on purpose-mapped.** Pause calls `Session.Abort`
   (destructive). Fix: re-implement as "signal the agent to wait for
   next user message before continuing."

---

## 6. Tests: what's there and what's missing

**Tested (unit, race-clean):**
- `internal/errs/` — sentinels + Wrap
- `internal/vault/...` — crypto, scrub, templates, use, audit, plugin
- `internal/task/filestore/` — YAML persistence + every Status transition
- `internal/project/filestore/` — multi-repo persistence
- `internal/mode/` — markdown → system prompt parsing
- `internal/agent/driver/` + `opencode/` — interface contract tests, mode constants
- `internal/container/isolation.go` + `podman` — IsolationProfile defaults, arg strings
- `internal/session/init.go` — phase 1 (Resolve), some phase 2, GenerateID
- `internal/session/runtime_container.go::pickImage` — stack detection
- `internal/cockpit/tui/` — bubble tea render tests against mocks

**Not tested:**
- end-to-end `session.Init` against a real `opencode serve` (no test environment for this)
- podman flag emission against actual `podman --version`, `podman run --help`
- any cross-package integration
- any concurrent-driver scenarios (multiple sessions at once)

**How to run:**
```bash
go test -race ./internal/...
go test -race -run TestInit ./internal/session/  # focused
go test -race -v ./internal/container/           # verbose for isolation profile
```

---

## 7. The mandatory build commands

After every change:
```bash
gofmt -w .
go vet ./internal/...
go test -race ./internal/...
git add -A && git commit -m "..."
```

Tarball/bundle for delivery:
```bash
cd /workspace && tar -czf agentjam.tar.gz --exclude='agentjam/.git' --exclude='agentjam/.agentjam' --exclude='agentjam/node_modules' agentjam/
cd /workspace/agentjam && git bundle create /workspace/agentjam.bundle --all
```

**NOTE:** `go mod tidy` requires network and has been broken in our sandbox
due to `muesli/ansi@20211031195517-c9f0611b4c70` returning 404 from the Go
proxy. On a normal dev machine `go mod tidy` works fine. Until then, the
prebuilt `go.sum` is fine for `go test ./internal/...`.

---

## 8. Style and convention rules

These are unwritten but enforced by the existing code:

- **Errors via `errs.Wrap(ErrXxx, "context: %w")`, never `fmt.Errorf`** —
  enables `errors.Is` calls to work against sentinels
- **One struct per file when possible**; long files are organized by
  top-down: package doc, types, helpers, methods, checks
- **YAML front-matter for persisted structs**; `json:` tags duplicate for
  any cross-package serialization
- **`errs.ErrXxx` as sentinels**, not ad-hoc strings, ever. Sentinels
  live in `internal/errs/errs.go`: `ErrNotFound`, `ErrAlreadyExists`,
  `ErrInvalid`, `ErrUnauthorized`, `ErrUnavailable`, `ErrTimeout`,
  `ErrCanceled`, `ErrUnsupported`
- **Tests use stdlib `testing` only**, no testify, no gomock
- **No `interface{}` in API signatures** — use named interfaces or generics
- **No exported globals** except pre-allocated constants and the `Compile-time
  check` pattern `var _ Foo = (*Bar)(nil)`
- **Drivers must respect `ctx`** — every method that does I/O; surface
  `ctx.Err()` via `errs.Wrap`
- **Channel-based event delivery** — drivers return `<-chan Event` from
  `Events()`; the channel is closed when the driver stops

---

## 9. Known gotchas (read these before you write code)

1. **Session struct has a `DriverID` field** (string) AND the
   `Runtime` interface has a `DriverID()` method. Don't confuse them.
   `Session.DriverID` is the persisted identifier; `runtime.DriverID()`
   is the live driver's id.

2. **`os/exec` for podman commands** — never reuse a context with
   cancellation for a long-running `Run`. Spawn a fresh sub-context.

3. **`podman port` output format** — my `discoverPortMapping` assumes
   lines like `127.0.0.1:49152` (or `0.0.0.0:49152`). It returns the
   first line if no `127.0.0.1:` is found. Edge case I haven't tested:
   IPv6 binding.

4. **`--userns keep-id`** — requires userns support in kernel (most
   distros have it on by default; Ubuntu 24+ and modern Fedora are fine).
   Without it, `podman run` will fail with an opaque error.

5. **`--storage-opt size=N`** for disk quota is silently ignored on
   storage drivers that don't support quotas. Don't bet the farm on
   disk caps being enforced.

6. **`opencode-sdk-go` types are version-pinned** to `v0.19.2` in go.mod
   but nothing tests that the actual API matches what I wrote in
   `internal/agent/driver/opencode/opencode.go`. The first integration
   run is a coin flip.

7. **The vault's `argon2id` parameters** are tuned for an interactive
   unlock: ~1 second on a modern CPU. Locked ⇒ agent can't inject creds.
   Acceptable, but it'll surprise users on slow machines.

8. **No graceful shutdown wiring.** A SIGINT during `agentjam session
   start --container` will orphan the container. Add signal handling in
   the CLI subcommand before long-running containers become the norm.

9. **The driver forwarder closes a channel on `Stop`** — but
   `Session.Driver.Events()` callers must guard with `_, ok := <-chan`
   if they want to detect closure vs just empty channel. Easy to miss.

---

## 10. Sandbox-specific traps (no Go installed by default)

The dev sandbox this was authored in has:
- **No Go** — was installed then removed; `/usr/local/go` is gone.
  Use: `curl -fsSL https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar xz -C /tmp`
  then `export PATH=/tmp/go/bin:$PATH`.
- **`muesli/ansi@20211031195517-c9f0611b4c70` returns 404 from the Go proxy.**
  This is a transitive dep of bubble tea → lipgloss → …
  Workaround for the dependency-cleanup step: edit `go.mod` to comment
  out the `github.com/aymerick/douceur` line (NOT the same dep, but the
  cleanup will be blocked by ANY unreachable indirect dep). I already
  did this; line in `go.mod` is marked `-- removed; unretrievable`.
- **No podman** — can't actually run a container session end-to-end.
  All podman behavior in this repo is verified by string-level tests
  on the args; nothing about the live runtime.

If you're picking this up and you DO have podman + Go: the first thing
to do is `go mod tidy && go build ./...` and run a real `agentjam
session start --task T-001 --container --detach` against a stub task.
That single end-to-end run will reveal half the issues listed above.

---

## 11. The 30-day plan (read this before committing to a different one)

**Week 1: integration hollowness** (closes 4 F's → C)
- Real git worktree integration (clone, branch, worktree add per agent)
- Egress filter via iptables in container netns (or podman firewalld)
- Live driver registry: runtime.Register(driver) + accessor
- Event bus: SSE on a local unix socket for `session logs`
- `session stop` actually stops the runtime

**Week 2: usable** (TUI gets real, sessions get costs)
- Take-over flow: `agentjam assume <session>`, TUI `a`/`r` keys
- Per-session token / cost tracking (driver-side, exposed to UI)
- `scripts/smoke.sh` end-to-end test against fake LLM endpoint
- macOS podman CI integration test

**Week 3: presentable** (web cockpit v0.4)
- stdlib `net/http` server, binds `127.0.0.1:<random>`, prints URL
- HTMX + Pico CSS for minimal but pretty UI
- SSE endpoint for live events
- Token auth → cookie session
- ~500 LOC

**Week 4: safe to keep using**
- Rate-limited GitHub API client (no surprise 429s)
- Per-session cost cap, configurable per mode
- Integration test suite under `internal/integration/`
- Real OpenCode server run in CI

---

## 12. What you (the new agent) should do first

Concrete, in order:

1. **Read `docs/RETRO.md`.** It's the honest assessment of what's done vs
   hollow and why. Half an hour of reading saves you a week of
   re-discovering what's actually wired.

2. **Run `go test -race ./internal/...`** on your machine (no podman, no
   OpenCode server needed). Confirm green.

3. **Open `cmd/agentjam/session.go` and trace `session.StartCmd`** end to
   end. Note the `streamEvents` lie. That's your first concrete bug to
   fix.

4. **Open `internal/session/runtime_container.go::Start`** and re-read
   `discoverPortMapping`. The string parsing is fragile; mentally run
   it against podman 5.x output once.

5. **Pick one of the F's in the retro and make it a D.** Web cockpit is
   the biggest user-facing win. Take-over flow is the most-aligned-with-
   the-spec. Your call.

6. **Run a real `agentjam session start --container --detach` end-to-end**
   the moment you have OpenCode + podman + git in your dev env. Write
   down what breaks. Half the F's will collapse.

7. **Don't add new abstractions.** We have enough. If you're writing
   `interface { Foo; Bar }` for a single implementation, just write
   the struct.

8. **Don't re-organize the file tree.** The current layout is mostly
   right. Renames cost review time and don't move us closer to v0.1.

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **Session** | one running agent + its bookkeeping record |
| **Task** | persistent work record, separate from any agent's chat |
| **Project** | multi-repo workspace, e.g. frontend+backend+shared-lib |
| **Mode** | system prompt; behavioral persona (assistant, agent, reviewer, …) |
| **Take-over** | swapping session mode from `agent` (autonomous) to `assistant` (interactive), keeping the same session |
| **Worktree** | per-agent git working copy of a repo, branched off the project default |
| **Injection template** | vault mechanism: a way to expose a credential to a command (env, file, stdin, wrapper, ssh-key, plugin) |
| **Driver** | the abstraction over agent backends (OpenCode today, custom tomorrow) |
| **Runtime** | the per-session abstraction over local-execution vs containerized-execution |
| **Isolation profile** | the hardened container defaults (caps, seccomp, network, etc.) |
| **Cockpit** | the UI surface for managing multiple sessions (TUI today; Web v0.4) |
| **Operator** | a `agentjam <command>` that scripts can call (not a UI surface) |
| **Scrubber** | vault-side string substitution that removes leaked credential values from command output before returning it to the agent |

---

## 14. Where I think the next agent's actual day-1 hour-by-hour goes

```
Hour 0–1:  Read this doc + RETRO.md + the 3 ADRs
Hour 1–2:  Skim all of cmd/agentjam/*.go, knowing the test matrix
Hour 2–3:  Run `go test -race ./internal/...`, confirm green
Hour 3–4:  Trace cmd/agentjam/session.go::sessionStartCmd by hand
Hour 4–5:  Read internal/session/runtime_container.go::Start in full
Hour 5–6:  Skim internal/vault/filestore/crypto.go to know what's there
Hour 6–8:  Pick a single F → D. Implement. Commit. Test.
```

By the end of day 1 you should have one not-hollow thing and a list of
the next five not-hollow things to do in priority order.

---

## 15. Things deliberately left blank

These are intentionally not specified here — they're future-decisions and
the new agent should ask, not invent:

- The exact HTML layout / pages of the web cockpit
- Theux for take-over in TUI/Web
- Whether vault daemon will be its own binary or a sub-command
- Plugin system beyond vault (general bus)
- Provider-by-provider (Anthropic native, Ollama, etc.) — we go through
  OpenCode SDK for v1

---

**TL;DR for the next agent:**

> The interface design and most of the security boundaries are real. The
> "this thing actually runs against a real agent and I can drive it from a
> browser" part is a stack of stubs. Work the F's and the B's up to A in
> order of user-perceptible impact. Don't add new abstractions. Run a real
> podman + OpenCode end-to-end test the day you can — the result will be
> ugly but actionable.

Welcome to the project. Have fun.
