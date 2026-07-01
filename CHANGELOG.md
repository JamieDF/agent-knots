# Changelog

All notable changes to harness are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Container isolation profile (`internal/container/isolation.go`)** — hardened-by-default `IsolationProfile` for every container session: non-root UID, all Linux capabilities dropped except the file-ops subset, read-only root filesystem, private network namespace, no-new-privileges, seccomp, tmpfs scratch space, cgroup CPU/RAM/PID/disk limits, deny-by-default egress (private subnets + cloud metadata blocked). Apply via `container.ApplyIsolation` in session init; runtimes read the profile and emit the corresponding podman flags. See ADR-004.
- **Hardened podman runtime flags** — `internal/container/podman/podman.go` now emits `--cap-drop=ALL` + `--cap-add` for kept caps, `--security-opt no-new-privileges:true` and `seccomp=runtime/default`, `--read-only`, `--tmpfs` per scratch path, `--pids-limit`, `--userns keep-id`, `--storage-opt` for disk quotas. Verified by new `podman_isolation_test.go`.
- **`privileged-debug` profile (`container.PrivilegedDebugProfile()`)** — opt-out path: run as root with `--privileged` and host network. The CLI gates this behind `--privileged-debug` with a console warning.
- **`harness session` subcommand (`cmd/harness/session.go`)** — start / list / show / stop / logs for sessions. Supports `--task`, `--project`, `--mode`, `--container`, `--image`, `--detach`, `--privileged-debug`. A session may be task-less (interactive) or task-driven; same flow either way.
- **Session init flow (`internal/session/init.go`)** — six phases: Resolve → Decide runtime → Prepare workspace → Start → Register → Prompt. Each phase logs context for diagnose-on-failure. Partial sessions record where they failed.
- **Runtime adapters (`internal/session/runtime.go` + `runtime_local.go` + `runtime_container.go`)** — `Runtime` interface with `LocalRuntime` (host) and `ContainerRuntime` (podman) implementations. Container runtime creates per-session worktree, hardens via `IsolationProfile`, runs the container, parses `podman port` to discover the host-side mapping, polls OpenCode's HTTP root until ready, then dials into it via the SDK.
- **ADR-004 (`docs/decisions/004-container-isolation.md`)** — full rationale for the default hardening: threat model, what we forbid, why not VM isolation in v1, alternatives considered (gVisor, no isolation, root, bind-mount-everything), and follow-ups (eBPF, Firecracker, runtime audit in cockpit).

### Changed

- `Session` struct extended with `Runtime` (local/container) and `Env` (per-session env vars). Existing sessions persisted without these fields load with empty defaults.
- `ContainerConfig` extended with `Privileged` and `ReadOnlyRootfs` fields; runtimes honor them.

## [0.1.0] - 2026-06-30

### Added

- Initial release of harness, a local-first orchestrator for AI coding
  agents.

#### Core interfaces

- `internal/agent/driver.Driver` — the abstraction every agent backend
  implements. OpenCode today, custom drivers tomorrow.
- `internal/vault.Vault` — credential storage with injection templates.
- `internal/task.Store` — persistent task system with progress logs.
- `internal/project.Store` — multi-repo project workspaces.
- `internal/container.Runtime` — abstraction over container engines.
- `internal/mode.Loader` — markdown → system prompt conversion.

#### Implementations

- `internal/vault/filestore` — AES-256-GCM encrypted file-backed vault
  with argon2id key derivation, 6 injection modes (env, file, ssh,
  stdin, wrapper, plugin), output scrubbing, and append-only audit log.
- `internal/task/filestore` — YAML file-backed task store with progress
  log, acceptance criteria gating, and step-level plan tracking.
- `internal/project/filestore` — YAML file-backed project store with
  active-project tracking.
- `internal/mode` — markdown mode loader with caching and reload.
- `internal/container/podman` — podman CLI-based container runtime.
- `internal/agent/driver/opencode` — OpenCode Go SDK adapter.

#### CLI

- `cmd/harness/` — Cobra-based CLI with subcommands:
  - `harness project` — list, create, switch, show, delete, active
  - `harness task` — list, new, show, status, assign, log
  - `harness vault` — init, unlock, lock, list, add, remove, show,
    template (list/add/remove), audit
  - `harness agent` — spawn, list (stub)
  - `harness cockpit` — stub
  - `harness version`

#### Modes

Six default modes as markdown files in `modes/`:

- `assistant` — interactive, waits for user
- `agent` — autonomous, spec-driven, works to completion
- `reviewer` — read-only, finds issues, structured output
- `security` — read-only, security audit with CWE tags
- `junior-dev` — cautious, asks questions, runs tests often
- `senior-dev` — confident, decisive, moves fast

#### Tests

- Unit tests across all core packages with table-driven subtests
- Race detector enabled (`go test -race`)
- Coverage: errs 75%, vault 97.6%, vault/filestore 68.8%, mode 90%+,
  task/filestore 90%+, project/filestore 90%+, container/podman 100%
  (parsers)

#### Documentation

- README with quickstart, architecture diagram, status
- LICENSE (MIT)
- CONTRIBUTING with development setup and conventions
- docs/architecture.md — full design document
- Plan document at PLAN.md (will be moved to docs/plan/ in 0.2)

### Notes

This is the first public release. All core interfaces are stable; we
expect minor breaking changes as the project evolves.