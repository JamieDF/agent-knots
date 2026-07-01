# Changelog

All notable changes to agentjam are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Renamed project from "harness" to "AgentJam".** Module path is now `github.com/JamieDF/agentjam`. CLI binary is now `agentjam` (single word). Default data directory is now `~/.agentjam/` (the old `~/.harness/` is auto-migrated on first run with a one-time stderr notice). Container image prefix is now `agentjam-agent-{stack}:{ver}` (e.g. `agentjam-agent-node:20`). Container labels are now `io.agentjam.managed` and `io.agentjam.exposed-port`. Vault marker is now `agentjam-vault-marker-v1`. See the commit history for the four-commit rename series.

> **Note:** This is a hard cutover for the encrypted vault. Any pre-existing encrypted vault stored under the prior marker cannot be unlocked after upgrade. Users with pre-existing state should run `agentjam vault export` BEFORE upgrading, then re-init the vault and re-add credentials. (In normal use the auto-migration of the home directory is sufficient; only encrypted blobs need re-init if they pre-date this release.)

## [0.1.0] - 2026-06-30

### Added

- Initial release of agentjam, a local-first orchestrator for AI coding
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

- `cmd/agentjam/` — Cobra-based CLI with subcommands:
  - `agentjam project` — list, create, switch, show, delete, active
  - `agentjam task` — list, new, show, status, assign, log
  - `agentjam vault` — init, unlock, lock, list, add, remove, show,
    template (list/add/remove), audit
  - `agentjam agent` — spawn, list (stub)
  - `agentjam cockpit` — stub
  - `agentjam version`

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