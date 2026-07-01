> **Note:** Captured under the prior project name "harness"; see CHANGELOG for the rename.

# ADR-004: Container isolation strategy for agent sessions

**Status:** Accepted
**Date:** 2026-06-30
**Supersedes:** —

## Context

`agentjam session start --container` runs an agent inside an isolated
container. The container needs:

- **Enough capability** to do real engineering work: run shell commands,
  install packages, edit files, run tests, talk to an LLM provider.
- **Strong enough isolation** that a misbehaving agent cannot compromise
  the host, read secrets, or interfere with other agents.

The threat model:

| Threat | Likelihood | Severity |
| --- | --- | --- |
| Agent deletes important host files | Medium (accidental `rm -rf`) | High |
| Agent reads SSH keys, `.env`, browser cookies | Medium | High |
| Agent installs persistent malware | Low | High |
| Agent uses all RAM/CPU | Medium | Medium |
| Agent exfiltrates code/credentials | Low | High |
| Kernel exploit escapes container | Very low | Catastrophic |
| Agent accesses local services (redis, postgres on 127.0.0.1) | Low | Medium |
| DNS rebinding hits cloud metadata endpoint | Low | High |
| Vault socket is read by escaped container | Low | Critical |

## Decision

We ship a hardened-default `IsolationProfile` applied automatically to every
container session. Users who need looser settings opt in per-session.

### Defaults

- **User**: container runs as the host user's UID/GID, not root
- **Capabilities**: drop ALL, add back only the file-operation ones
  (`CAP_CHOWN`, `CAP_DAC_OVERRIDE`, `CAP_FOWNER`, `CAP_SETUID`, `CAP_SETGID`,
  `CAP_FSETID`, `CAP_SETFCAP`)
- **`--privileged`**: never (no opt-out at the CLI surface)
- **`--security-opt no-new-privileges:true`**: always
- **`--security-opt seccomp=runtime/default`**: always
- **Root filesystem**: read-only
- **PID namespace**: private
- **IPC namespace**: private
- **UTS namespace**: private
- **Mount propagation**: no sharing with host
- **Network**: by default, no host network; egress allowlist via filter

### Mounts

The agent sees ONLY its assigned worktree, plus the vault socket:

- `/workspace` → `~/work/<project>/.agentjam/worktrees/<agent>/<repo>` (RW)
- `/run/agentjam/vault.sock` → host unix socket (RW, but not the underlying
  secret files)
- `/tmp` → tmpfs (RAM-backed, auto-cleaned)
- Nothing else from the host is mounted. `~/.ssh`, `~/.aws`, `~/.config`,
  `/etc`, `/var`, `/home` are all invisible.

### Network

The container gets a private network namespace. **Network access is
deny-by-default** — the agent has to ask via policy:

- **Always allow**: the configured LLM provider's API endpoint
  (e.g. `api.anthropic.com`, `api.openai.com`).
- **Always allow**: the vault daemon (already proxied via unix socket).
- **Conditionally allow**: package registries (`registry.npmjs.org`,
  `pypi.org`, `proxy.golang.org`). Each requires explicit `egress` policy.
- **Always deny**: `169.254.0.0/16` (link-local), `127.0.0.0/8` (loopback),
  `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (private nets),
  `169.254.169.254` (cloud metadata).
- **Rate limit**: 1000 req/min per container to limit exfiltration.

Implementation: a small `nftables`/`iptables` rule set injected via the
podman `--network` option, OR a userspace egress proxy. v1 ships the simple
version: iptables rules pushed into the container's network namespace at
start, then dropped when container stops. Future versions can use eBPF or
Cilium for richer policy.

### Resource caps

- **CPU**: 2.0 cores (configurable per project; project can request up to
  host's total)
- **Memory**: 4 GiB
- **Disk writes**: 10 GiB (overlay-fs quota)
- **PIDs**: 512
- **Wall-clock**: 8 hours max runtime, then auto-stop

These are enforced by cgroups. Exceeding them kills the agent's current
process; the agent's session is marked `error` with reason
`resource-exceeded`.

### Vault access

The vault is on the host. The container's only host-side interaction is
`/run/agentjam/vault.sock`. The vault daemon:

- Listens on the unix socket **only**
- Permissions on the socket: `0o660` with group `agentjam`
- Validates the caller via SO_PEERCRED (the calling process's PID/UID)
- Refuses connections from any UID other than the host user
- **Never** reads back from the container; only the container can ask

If the agent uses `vault://github/work` in a `gh pr create` command:

1. Agent sends a request to `vault.sock` describing the use
2. Host's vault daemon looks up the credential, runs `gh pr create` with the
   token injected via env-var template, captures stdout/stderr
3. Vault daemon scrubs the response (replaces any token-shaped string with
   `[scrubbed]`)
4. Returns scrubbed output to the container
5. Logs the use in the audit log

The raw token never appears on the container's filesystem, env, or network.

### What we DON'T support in v1

- `--privileged` containers
- `--network host`
- Mounting arbitrary host paths (we only allow the worktree dir computed by
  agentjam)
- Disabling seccomp
- Running as root inside the container

If a user needs any of these, they should run the agent outside of
agentjam's container mode and accept the threat model themselves. We're not
going to expose footguns in the CLI.

### Image strategy

We ship per-stack default images and allow override:

| Stack | Default image |
| --- | --- |
| Node.js / TypeScript | `agentjam-agent-node:20` |
| Python | `agentjam-agent-python:3.12` |
| Go | `agentjam-agent-go:1.23` |
| Rust | `agentjam-agent-rust:1.82` |
| Generic | `agentjam-agent-base:latest` |

The project's `container.image` field overrides (point to your own image).
The project's `container.dockerfile` field triggers a build on first use
(Dockerfile lives at `./Dockerfile.agent`).

Image auto-detection: read `package.json`, `pyproject.toml`, `go.mod`,
`Cargo.toml` and pick the matching image.

### Why not VM isolation?

Podman rootless + seccomp + capabilities is enough for the agent threat
model (agents I trust to work on my repos). For truly untrusted code
(random GitHub repos), containers share the host kernel — VM isolation
(Firecracker, Qubes, etc.) would be safer. We may add a
`ContainerRuntime` implementation backed by a microVM in v2.

## Alternatives considered

1. **gVisor (runsc)** — kernel-emulation layer. Slower startup, lower
   fidelity for some syscalls. Overkill for our threat model.
2. **No isolation (local agents only)** — simpler, but the threat of an
   accidental `rm -rf ~` is real and we've seen users ask for stronger
   safety. We keep local mode as an opt-in (no `--container` flag).
3. **Run as root (Docker default)** — too easy for a typo to brick the
   user. Out.
4. **Bind-mount everything in `~`** — minimal friction, but a malicious
   prompt can read SSH keys. Out.

## Consequences

- **Positive**: safe-by-default; "I ran an agent and it didn't brick my
  laptop" is the explicit promise.
- **Positive**: vault stays on host, no secrets on disk inside container.
- **Negative**: ~5-10s extra startup time vs. unrestricted podman (cap
  drops + seccomp profile load + network policy setup).
- **Negative**: agents can't easily install system-level packages inside
  the container (need to use `pip install --user`, `npm install --prefix`,
  etc.). We accept this — it's the right default.
- **Negative**: we have to maintain the network policy implementation
  (iptables in v1).

## Follow-ups

- Replace iptables rules with eBPF for richer policy and better logging.
- Add a `ContainerRuntime` backed by Firecracker microVMs for users who
  need VM-level isolation.
- Surface per-session network/audit log in the cockpit.
