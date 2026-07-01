> **Note:** This document was originally authored under the prior project name "harness"; references to "agentjam" reflect the rename. See CHANGELOG.

# Roadmap

This is a high-level sketch of where agentjam is headed. It's not a
commitment — features get added, dropped, and reordered based on what
users actually need.

## v0.1 (current)

Foundation. Core interfaces, file-backed implementations, CLI, modes.

## v0.2 — Container integration

- [ ] Container runtime spawn helper: clone repo into a container,
  install deps, run baseline tests, run agent loop, run final tests,
  push branch, open PR.
- [ ] Worktree management per agent session.
- [ ] Network policy enforcement (default-deny egress, allowlist for
  registry, vault daemon, gh).
- [ ] Per-container resource caps.

## v0.3 — TUI cockpit

- [ ] Bubble Tea-based TUI cockpit.
- [ ] Multi-agent list with live status.
- [ ] Per-agent focus view (zoom in on one agent's events).
- [ ] Quick-switch keybindings (j/k or 1-9).
- [ ] Assume / relinquish control flows.
- [ ] Task and vault management within the TUI.

## v0.4 — Web cockpit (primary)

- [ ] Web GUI as primary management surface. **Binds to
  `127.0.0.1:<random-port>` by default** (printed at startup). Browser
  access is the whole point. Remote access (LAN/WAN) is the user's
  responsibility — typical setup is a Cloudflare Tunnel with Auth in
  front of the localhost port.
- [ ] Token-based auth: one token generated on first start, saved to
  `~/.agentjam/cockpit.token` (mode 0600). Browser prompts once, cookie
  issued after (`Secure`, `HttpOnly`, `SameSite=Strict`). All
  authenticated requests carry the cookie; SSE connections revalidate.
- [ ] Real-time event streaming via Server-Sent Events (SSE) — single
  one-way HTTP stream keeps the implementation small. WebSocket
  deferred until we need browser→server prompts.
- [ ] Multiple agents visible side-by-side.
- [ ] Diffs and code rendered with syntax highlighting.
- [ ] Mobile-friendly layout.
- [ ] **v0.4.1** — `--bind 0.0.0.0` opt-in for LAN access. Auth still
  required. Refuse non-localhost bind without a tunnel or TLS cert.
  Add `--tunnel` (Cloudflare quick tunnel) for zero-config remote.

## v0.5 — Multi-agent orchestration

- [ ] Active agent registry (in-process).
- [ ] Concurrent agent management from the cockpit.
- [ ] Cross-agent shared scratchpad.
- [ ] Conflict detection when two agents edit the same file.
- [ ] Result aggregation across multiple agents.

## v0.6 — Observability

- [ ] Session replay (click any past action, see the prompt + context
  that drove it).
- [ ] Time-spent and tokens-per-step analytics.
- [ ] Cost tracking per session / task / day.
- [ ] Budget alerts (50/80/100% of budget).
- [ ] Session export (Markdown, JSON).

## v0.7 — Provider expansion

- [ ] Direct provider integrations beyond OpenCode's built-in (for cases
  where OpenCode doesn't support what the user wants).
- [ ] Fallback chains (try primary, fall back to secondary on error or
  rate limit).
- [ ] Custom provider plugins.

## v1.0 — Stability and polish

- [ ] Stable public API.
- [ ] SemVer commitment (no breaking changes within v1.x).
- [ ] Performance: large task histories, many concurrent agents.
- [ ] Documentation: every interface documented, every command has
  examples, every mode has rationale.
- [ ] Installer: `curl ... | sh` for macOS / Linux / Windows.
- [ ] Update mechanism.

## Future (post-1.0, parking lot)

These are interesting ideas we may or may not pursue. Not committed.

- **Multi-user support.** Per-user vaults, audit logs, RBAC.
- **Cloud sync.** Optional encrypted sync via user's own cloud storage.
- **Cloud-hosted version.** A hosted agentjam for teams.
- **Mobile companion.** Mobile UI for monitoring agents on the go.
- **IDE plugins.** VSCode, JetBrains.
- **WASM agent sandboxes.** Faster, lighter isolation than containers.
- **Firecracker microVMs.** Stronger isolation for untrusted code.
- **Voice input.** Talk to your agents.
- **Visual reasoning graphs.** See the agent's reasoning as a graph.

## How to influence the roadmap

- Open an issue describing the use case.
- Upvote existing issues you care about.
- Send a PR that aligns with a roadmap item.
- Propose new items via the [decision record
  process](decisions/).