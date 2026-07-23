# Feature Inventory

**Date:** 2026-07-23 (supersedes the 2026-07-20 audit this file originally was)
**Purpose:** Complete catalog of what agent-knots can do — backend, CLI, web
GUI, TUI. Everything here was re-verified by reading the actual current
route/command/screen definitions, not by trusting the previous version of
this file or inferring from other docs.

The original version of this file was written *for* the "Atelier" web
cockpit redesign — a pre-redesign gap analysis. That redesign (plus several
rounds of real-usage bug fixing) has since shipped; this rewrite reflects
what's actually true now. See `roadmap.md` and `CHANGELOG.md`'s
`[Unreleased]` section for the full history of what changed and why.

Legend: **Web** = React SPA · **TUI** = Textual terminal UI · **CLI** =
`agent-knots` command · **Backend** = implemented, reachable by at least
one surface · **Agent-only** = a tool the *agent* can call, no human-facing
UI anywhere · 🚫 = not implemented at all

---

## 1. Sessions (agent runtime)

| Capability | CLI | Web | TUI | Notes |
|---|---|---|---|---|
| Start a session (model, task, project, mode, prompt) | `session start` | `POST /api/sessions`, "New Session" dialog | 🚫 | TUI still **cannot start sessions** — CLI or web only. Unchanged from the original audit. |
| List sessions | `session list` | `GET /api/agents`, Dashboard agent cards | Agent list `DataTable` | |
| Stop / delete a session | 🚫 | Two distinct actions now: composer "■ Stop" cancels only the current turn (`POST /api/agent/{id}/interrupt`) — the session stays open, send another message to continue; header "✕ Delete" ends the session for good (`DELETE /api/agent/{id}`, confirm prompt) | `d` key (delete only — no separate interrupt-only action in the TUI) | Still no CLI stop/delete command |
| Start a long-running process (dev server, watcher) without it being killed | 🚫 | Shell tool's `background=true` — starts detached, returns immediately with a pid + log file, isn't subject to the tool's timeout-kill. Tracked per-session and killed when the session ends | 🚫 | **New this cycle** — previously the only way to keep something running past a single tool call was an agent hand-rolling `nohup cmd &`, which several real sessions got stuck fumbling with before this existed |
| Send a follow-up message (multi-turn chat) | 🚫 (foreground session only, via stdin flow) | `POST /api/agent/{id}/send`, Agent Thread composer | 🚫 | **TUI still can't send messages** — view-only + assume/relinquish. Unchanged. |
| Take over / hand back control | 🚫 | Single Autonomous toggle on task-attached sessions (`POST /api/agent/{id}/autonomous`) — off interrupts the current turn and pauses self-continuation, tools still work; on resumes the task with a "pick up where you left off" nudge. Replaces the old separate Assume/Relinquish buttons and DRIVING/WATCHING chip. The low-level `POST /api/agent/{id}/assume`/`/relinquish` routes (raw mode flip, no interrupt/resume) still exist and are still tested but no longer called by the web UI. | `a`/`r` keys (still the old raw mode flip, not the new toggle's interrupt/resume behavior) | |
| Set mode to **reviewer** or **security** | `--mode reviewer\|security` at start only | 🚫 | 🚫 | Unchanged — still CLI-only, still only settable at session start. Web's New Session dialog still only offers Agent/Assistant. |
| Live event stream (thinking, tool calls, results) | Foreground stdout | SSE (`GET /api/agent/{id}/events`), structured JSON | Focus screen poll | **Fixed since the original audit**: real fan-out (`Session.subscribe()`/`_broadcast()`) — multiple browser tabs no longer race for events. Agent Thread also has a replay scrubber over a session's own event history once it's ended (not the same thing as SSE `Last-Event-ID` reconnect, which still doesn't exist). |
| Runtime selection | Only via project's `runtime` field or global `settings.yaml` | Settings → Workspaces edit form has a runtime field | 🚫 | In-process is the only real runtime — a second, subprocess-isolated one existed but never actually worked (see `docs/RETRO.md`) and was deleted rather than fixed. No per-session CLI flag either way. |
| Token / cost tracking per session | `session list` output | Agent cards, topbar stats | Agent list columns | Token counts are real; cost is still a flat $0.30/1M estimate regardless of actual provider/model |
| Detach mode (`--detach`) | 🚫 stub | n/a | n/a | Unchanged — CLI prints "not yet implemented" and exits |
| Sub-agent delegation (`delegate_task`) | Agent-only | Agent-only | Agent-only | **Fixed since the original audit**: the tool is appended to the tool list *before* the `Agent` is constructed, so it actually reaches the agent now (previously appended after — likely never usable). Parent monitors via `read_task`. |
| Memory injection (cross-session context) | Automatic | Automatic | Automatic | Unchanged — invisible, happens on session start when the task has prior progress-log entries |
| Steering nudges (criteria keyword-match) | Automatic | Automatic | Automatic | Unchanged — advisory only, logs a suggestion, never marks anything itself |

---

## 2. Tasks

| Capability | CLI | Web | TUI | Notes |
|---|---|---|---|---|
| Create | `task create <title> --priority --criteria ...` | `POST /api/tasks`, TaskDialog | 🚫 | **Fixed since the original audit**: TaskDialog now has full tags/criteria/steps/review-gate editors plus a "✨ Draft with agent" button, not just title/description/priority. New tasks default to `draft` status (previously `open`). |
| List / filter (status, project, tags, limit) | `task list` | `GET /api/tasks`, Tasks screen (Board + List tabs) | 🚫 | TUI still has **no task screen at all** |
| Show full detail | `task show` | TaskDetail view | 🚫 | |
| Update title / status / assignment | `task update` | TaskDetail edit form | 🚫 | |
| Update description / tags / acceptance criteria | 🚫 (CLI `update` still has no `--description`/`--criteria`/`--tag` flags) | **Fixed since the original audit**: `UpdateTaskRequest` now has all these fields; editing a task's description/tags/criteria actually persists (previously silently dropped) | 🚫 | CLI is the one still behind here — web fixed, CLI wasn't touched |
| Delete | `task delete` | `DELETE /api/tasks/{id}` | 🚫 | |
| **Mark an acceptance criterion met** | 🚫 (still no CLI command) | **Fixed since the original audit**: `POST /api/tasks/{id}/criteria/toggle`, clickable checkboxes in TaskDetail | 🚫 | Previously agent-tool-only; now a human can do this directly from the web UI. CLI still can't. |
| Add a step to a task's plan | 🚫 (agent tool only) | 🚫 (steps shown read-only in TaskDetail, editable only at creation via TaskDialog) | 🚫 | Unchanged — `add_step` is still agent-only after creation |
| View progress log | `task show` | TaskDetail | 🚫 | |
| View steps (read-only after creation) | `task show` | TaskDetail | 🚫 | |
| Kanban board | n/a | **Fixed since the original audit**: configurable stages (Workflows screen) cover all 8 `TaskStatus` values — `blocked`/`planned` surface as badges on their parent column's cards instead of vanishing. Drag-and-drop between columns. | 🚫 | Tasks list view (List tab) still correctly covers all 8 too |
| Task dependencies | 🚫 (no CLI flag) | **New this cycle**: `dependencies: list[str]` on `Task`, a chip picker in TaskDialog, `🔗 DEP` badge on blocked cards, `unmet_dependencies()` refuses the `in_progress` transition and the "Start" button/`POST /api/sessions` pre-flight until every dependency is `done` | 🚫 | Dangling dependency ids (e.g. a deleted task) are treated as non-blocking rather than a permanent lock |
| Task lifecycle enforcement | Enforced in `TaskStore` regardless of surface | | | `done` requires all acceptance criteria met, **and** (new) a real review-gate: a task with `review_gate != "none"` must pass through `review` status first — previously the field was persisted and displayed but not enforced. **Security fix this cycle**: the transition into `done` is now actor-aware — an agent's own tool call is always `actor="agent"` and gets refused past `review`; only the web's human-driven `PATCH /api/tasks/{id}` passes `actor="human"`. Previously an agent could call `update_task_status('review')` then `update_task_status('done')` back-to-back in the same turn and self-approve with zero human oversight. Terminal tasks (`done`/`abandoned`) still can't be transitioned further from any surface. |

---

## 3. Vault (encrypted credential store)

**Fixed since the original audit — Vault now has a real web UI.** This was
called out as "the single biggest backend-capability-with-no-GUI gap"; it
no longer is.

| Capability | CLI | Web | TUI |
|---|---|---|---|
| Init / unlock / lock / status | `vault init/unlock/lock/status` | Settings → Vault section: passphrase form for locked/uninitialized, "Lock" button when unlocked | 🚫 |
| Add / list / show / remove a credential | `vault add/list/show/remove` | Settings → Vault: credential list with template chips, "+ Add credential", delete | 🚫 |
| Injection templates (env / file / stdin / command-wrapper) | `vault template add/list/show/remove` | Read-only chips on each credential row (`env:KEY`, `file:path`, `wrapper`) — no template *editor* in the web UI yet, CLI-only for creating/editing templates | 🚫 |
| Audit log | `vault audit` | Settings → Vault: audit log table (timestamp, action, credential, caller) | 🚫 |
| Actually *using* a credential in an agent's tool call | 🚫 | 🚫 | 🚫 | No `vault_use` agent tool exists yet — unchanged, still on the roadmap |

Values never reach the web client — the API only ever returns metadata
(ids, descriptions, template shapes, timestamps), never raw credential
values, matching the CLI's existing security posture.

---

## 4. Projects / Workspaces

| Capability | CLI | Web | TUI |
|---|---|---|---|
| Create | `project create` | `POST /api/workspaces`, Settings → Workspaces "+ Add workspace" (with a folder-picker + GitHub-remote detection) | 🚫 |
| List | `project list` | `GET /api/workspaces` (excludes archived by default) | 🚫 |
| Show detail | `project show` | (list only, no detail view) | 🚫 |
| Update name / description / repository / tags / runtime | `project update` | **Fixed since the original audit**: `PATCH /api/workspaces/{id}` now has a real edit form (`WorkspaceDialog`) — previously the route and API client existed but no UI called it | 🚫 |
| Update default branch | `project update --branch` | Still 🚫 — `UpdateWorkspaceRequest` has no `default_branch` field. Unchanged from the original audit; CLI-only. | 🚫 |
| Archive / unarchive | 🚫 | **New since the original audit**: `archived` flag, hidden from the topbar scope switcher and Dashboard by default, dedicated Active/Archived sections in Settings | 🚫 |
| Delete | `project delete` | `DELETE /api/workspaces/{id}`, now with a confirm prompt (previously deleted immediately with no confirmation) | 🚫 |
| Filter tasks/sessions by active workspace | n/a | Yes — `workspaceContext.tsx` persists scope to both a `?ws=` URL param and `localStorage`, syncs across navigation | 🚫 |

CLI and web are further apart here than the original audit found — the web
side gained an edit form and archive/unarchive that the CLI doesn't have
(no `project archive` command).

---

## 5. Tools

| Capability | CLI | Web | TUI |
|---|---|---|---|
| List built-in tools (12: editor, shell, calculator, think + 8 task tools) | 🚫 | Settings → Tools section, **and** the still-orphaned `/tools` route (`ToolManager.tsx`) | Tools screen (`t`) |
| Enable / disable a built-in tool | 🚫 | Settings → Tools | `t` key |
| Add / edit / delete a custom shell-command tool | 🚫 | Settings → Tools | Add: still a placeholder ("...coming soon..."). Delete: `d` key works. |
| View custom tool detail (`GET /api/tools/{name}`) | 🚫 | Route exists, still unused by any frontend code | 🚫 |

**`ToolManager.tsx` is still a genuine orphaned duplicate**, unchanged from
the original audit — `Settings.tsx`'s Tools section (linked in the topbar
nav) and `/tools` (routed, but not in `Topbar.tsx`'s `NAV_ITEMS` — reachable
only by typing the URL) do the same thing. Worth consolidating.

No CLI tool-management commands exist — unchanged, web/TUI only.

---

## 6. Settings / Model Provider

| Capability | CLI | Web | TUI |
|---|---|---|---|
| View current settings | 🚫 (`settings show` is still a stub: "Not yet implemented") | `GET /api/settings`, Settings page | 🚫 |
| Edit model/API key/base URL/mode/runtime | Manual YAML edit or env vars only | `PUT /api/settings`, Settings + first-run Setup Wizard | 🚫 |
| Multiple providers, pick a default | n/a | **New since the original audit**: add/remove providers, "Set default" per provider (Settings → Model providers) | 🚫 |
| First-run setup wizard | n/a | Yes — auto-triggers when unconfigured | 🚫 |
| `default_mode` field | Not documented, not settable via any UI | Still not exposed in Settings. Unchanged — open item. | 🚫 |
| **Section navigation** | n/a | **New since the original audit**: Settings grew to 8 sections (Usage, Providers, Tools, Policies, MCP servers, Integrations, Vault, Workspaces) with a sticky side nav that jumps to and highlights the current section | 🚫 |

The CLI `settings` command group is still entirely a stub.

---

## 7. Cockpit shell (auth, layout, navigation)

| Capability | Web |
|---|---|
| Auth | Token-based: cookie, `?token=` query param (for SSE), `Authorization: Bearer` header — all now going through the same `verify_token()` constant-time compare (previously `server.py` reimplemented its own inline check, timing-attack-unsafe). Login page + form. **Fixed this cycle**: the query-token login previously only worked for `/api/*` paths, so the printed one-click cockpit URL (`http://host:port/?token=...`, path `/`) bounced to the login page instead of logging in — now accepted on any path, with the token stripped from the URL after it sets the cookie. |
| Nav (Topbar) | Dashboard, Tasks, Review, Workflows, Settings. Vault's separate top-nav entry was folded into a Settings section (`/vault` redirects to `/settings#vault`). Tools (`/tools`) is still not linked — see §5. |
| Views | Dashboard, Tasks (Board/List tabs, drag-and-drop), TaskDetail, **Agent Thread** (chat-style: agent/user turns anchor left/right, no avatars, markdown-rendered responses that also open any URL the agent mentions into the Browser tab, drag-to-resize chat/rail split clamped to 5–95% of the row, replay scrubber once ended; 4 right-rail tabs — **Terminal** (a real PTY-backed shell via xterm.js and a websocket, in the agent's own working directory, stays connected across tab switches), **Files** (editor-only touches, click to preview content), **Commands** (every shell invocation with a timestamp), **Browser** (a real multi-tab mini-browser — address bar, open/close tabs, a chat link opens in a new tab); composer's watching state is a banner above the input rather than a locked-out state — typing and sending assumes control automatically), **Review** (git-derived diff queue, approve/reject), **Workflows** (stage config + agent role/trigger config), Settings (9 sections incl. Vault and Accessibility — app-wide font size/family), ToolManager (still orphaned) |
| Live event rendering | Structured JSON events (`events.py::serialize_event()`), not pre-rendered HTML — the frontend owns all rendering. Consecutive same-type message/thinking deltas merge into one growing bubble rather than rendering each raw delta as its own fragment. |
| Mobile support | 🚫 still not implemented (on roadmap) |

TUI still has no auth (local-process access only) and no equivalent of
Tasks/Review/Workflows/Settings/Vault — just agent list → focus → tools.

---

## 8. Everything with literally no human-facing UI anywhere

Unchanged from the original audit — these are still agent-only:

- **`add_step`** — adding a step to a task's plan after creation.
- **`delegate_task`** — spawning a sub-agent on a sub-task (now actually
  reaches the agent — see §1 — but still no human-triggerable equivalent).
- **`validate_task_output`** — internal validation, not meant to be
  human-triggered, fine as-is.

`mark_criterion_met` is no longer in this list — humans can do it from
Task Detail now (§2).

---

## 9. Known gaps still worth fixing

- **Two tool-management UIs**: `Settings → Tools` and orphaned `/tools`
  (`ToolManager.tsx`). Unchanged from the original audit.
- **Vault template editing**: templates can be viewed (as chips) in the
  web UI but only created/edited via the CLI.
- **CLI task editing** lags the web: no `--description`/`--criteria`/
  `--tag` flags on `task update`, even though the web API supports all of
  them now.
- **No CLI workspace archive** command, even though the web UI has one.
- **`default_mode` setting** has no UI anywhere.
- **TUI**: can't start sessions, can't send messages, no task screen, "add
  custom tool" is a placeholder. All explicitly deprioritized while the
  web cockpit was the redesign focus, not accidental gaps.
- **Mobile-responsive layout** doesn't exist yet.
- **Reviewer/security session modes** are real (backend) but only
  reachable via CLI at session start — no web UI exposes them.

---

## 10. Summary: what's left after the redesign

Compared to the original audit's "what a GUI-primary redesign needs to
add" list — 6 of 8 items are now done (Vault UI, task editing, criteria
completion UI, Kanban's missing columns, workspace edit form). What's
genuinely still open:

1. **Container runtime** — full filesystem + network sandboxing, still
   the biggest security-relevant gap (see `docs/RETRO.md`).
2. **Consolidate the duplicate tools UI** — cheap, still not done.
3. **Reviewer/security mode** exposed somewhere outside the CLI, if
   that's still wanted.
4. **TUI parity** (session start/send, task screen) — an explicit
   non-goal for now, not forgotten.
5. **Mobile support**.
6. **Vault template editing in the web UI** (currently view-only there).

Everything else audited in the original version of this file — sessions,
tasks CRUD, projects, tool enable/disable, settings, auth — remains real
and working.
