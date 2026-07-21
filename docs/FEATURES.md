# Feature Inventory

**Date:** 2026-07-20
**Purpose:** Complete catalog of what agent-knots can do — backend, CLI, web
GUI, TUI — for the upcoming web GUI redesign. Everything here was verified
by reading the actual route/command/screen definitions, not inferred from
docs.

Legend: **Web** = React SPA · **TUI** = Textual terminal UI · **CLI** =
`agent-knots` command · **Backend** = implemented, reachable by at least
one surface · **Agent-only** = a tool the *agent* can call, no human-facing
UI anywhere · 🚫 = not implemented at all

---

## 1. Sessions (agent runtime)

| Capability | CLI | Web | TUI | Notes |
|---|---|---|---|---|
| Start a session (model, task, project, mode, prompt) | `session start` | `POST /api/sessions`, "New Session" dialog | 🚫 | TUI **cannot start sessions** — CLI or web only |
| List sessions | `session list` | `GET /api/agents`, Overview agent cards | Overview `DataTable` | |
| Stop / delete a session | 🚫 | `DELETE /api/agent/{id}` | `d` key | No CLI stop/delete command — once started via CLI, killing it requires web or TUI |
| Send a follow-up message (multi-turn chat) | 🚫 (foreground session only, via stdin flow) | `POST /api/agent/{id}/send`, chat box | 🚫 | **TUI can't send messages at all** — view-only + assume/relinquish |
| Assume control (agent → assistant) | 🚫 | `POST /api/agent/{id}/assume`, button | `a` key | |
| Relinquish control (assistant → agent) | 🚫 | `POST /api/agent/{id}/relinquish`, button | `r` key | |
| Set mode to **reviewer** or **security** | `--mode reviewer\|security` at start only | 🚫 | 🚫 | These 2 modes exist in the backend (`_build_system_prompt`) but the web's New Session dialog only offers Agent/Assistant, and assume/relinquish only toggle agent↔assistant. Reviewer/security are CLI-only and only settable at session start, never mid-session anywhere. |
| Live event stream (thinking, tool calls, results) | Foreground stdout | SSE (`GET /api/agent/{id}/events`) | Focus screen poll | Web SSE has no fan-out — two browser tabs on the same agent race for events, one silently misses them. No reconnect/replay (`Last-Event-ID`) support. |
| Runtime selection (in-process vs subprocess) | Only via project's `runtime` field or global `settings.yaml` | Settings page ("Model Provider" tab has a runtime field) | 🚫 | No per-session CLI flag (`session start` has no `--runtime`) |
| Token / cost tracking per session | `session list` output | Agent cards, topbar stats | Overview table columns | Token counts are real (from model response metadata); cost is a flat $0.30/1M estimate regardless of actual provider/model |
| Detach mode (`--detach`) | 🚫 stub | n/a | n/a | Explicitly not implemented — CLI prints "not yet implemented" and exits |
| Sub-agent delegation (`delegate_task`) | Agent-only | Agent-only | Agent-only | The agent calls this itself to spawn a sub-session on a new task; no human UI triggers it directly. Parent monitors via `read_task`. |
| Memory injection (cross-session context) | Automatic | Automatic | Automatic | Invisible — happens automatically when starting a session with a `task_id` that has prior progress-log entries |
| Steering nudges (criteria keyword-match) | Automatic | Automatic | Automatic | Advisory only — logs a suggestion to the task's progress log, never marks anything itself |

---

## 2. Tasks

| Capability | CLI | Web | TUI | Notes |
|---|---|---|---|---|
| Create | `task create <title> --priority --criteria ...` | `POST /api/tasks`, Create Task dialog | 🚫 | **Web's Create Task dialog has no acceptance-criteria field** — title/description/priority only. CLI supports `--criteria` at creation; web can only add criteria after creation via edit. |
| List / filter (status, project, tags, limit) | `task list` | `GET /api/tasks`, Board + Tasks views | 🚫 | TUI has **no task screen at all** |
| Show full detail | `task show` | TaskDetail view | 🚫 | |
| Update title / status / assignment | `task update` | TaskDetail edit form (partial — see bugs) | 🚫 | |
| Update description | `task update`? **no** — CLI `update` also lacks a `--description` flag | Edit form has a field but **silently no-ops** | 🚫 | Backend `UpdateTaskRequest` model has no `description` field at all — Pydantic drops it. Neither CLI nor web can currently edit a task's description after creation. |
| Update acceptance criteria | 🚫 (CLI `update` has no `--criteria` flag either) | Edit form has a field but **silently no-ops** | 🚫 | Same root cause — `UpdateTaskRequest` has no `acceptance_criteria` field |
| Update tags | 🚫 | Edit form has a field but **silently no-ops** | 🚫 | Same — no `tags` field on `UpdateTaskRequest` |
| Delete | `task delete` | `DELETE /api/tasks/{id}` | 🚫 | |
| **Mark an acceptance criterion met** | 🚫 (agent tool only, no CLI command was added for it) | 🚫 | 🚫 | `mark_criterion_met` exists only as an agent-callable tool. **No human — CLI, web, or TUI — can mark a criterion met directly.** Since "done" is now hard-gated on all criteria being met, a human can currently only unstick a task by editing the YAML file by hand. |
| Add a step to a task's plan | 🚫 (agent tool only) | 🚫 (steps shown read-only in TaskDetail) | 🚫 | Same pattern — `add_step` is agent-only |
| View progress log | `task show` | TaskDetail | 🚫 | |
| View steps (read-only) | `task show` | TaskDetail | 🚫 | |
| Kanban board | n/a | Board view — **6 columns** | 🚫 | `TaskStatus` has 8 values (draft, open, planned, in_progress, blocked, review, done, abandoned). Board only renders 6 — tasks in `blocked` or `abandoned` have no column and **disappear from the board entirely**. The Tasks list view (sidebar filter) correctly covers all 8. |
| Task lifecycle enforcement | Enforced in `TaskStore` regardless of surface | | | `done` requires all acceptance criteria marked met (new this session); terminal tasks (`done`/`abandoned`) can't be transitioned further from any surface |

---

## 3. Vault (encrypted credential store)

**This entire feature has zero web or TUI presence. It is 100% CLI-only.**
No `/api/vault/*` route exists anywhere in `server.py`, and no vault
screen exists in the TUI.

| Capability | CLI | Web | TUI |
|---|---|---|---|
| Init / unlock / lock / status | `vault init/unlock/lock/status` | 🚫 | 🚫 |
| Add / list / show / remove a credential | `vault add/list/show/remove` | 🚫 | 🚫 |
| Injection templates (env / file / stdin / command-wrapper) | `vault template add/list/show/remove` | 🚫 | 🚫 |
| Audit log | `vault audit` | 🚫 | 🚫 |
| Actually *using* a credential in an agent's tool call | 🚫 | 🚫 | 🚫 | No `vault_use` agent tool exists yet — templates are stored metadata only, nothing consumes them automatically during a session (tracked on the roadmap). |

Given "GUI primary" is the stated direction, **this is the single biggest
backend-capability-with-no-GUI gap** — the vault is fully built (real
AES-256-GCM + argon2id crypto, genuinely the most solid subsystem in the
codebase) and completely invisible to anyone who never touches the CLI.

---

## 4. Projects / Workspaces

| Capability | CLI | Web | TUI |
|---|---|---|---|
| Create | `project create` | `POST /api/workspaces`, Settings → Workspaces tab | 🚫 |
| List | `project list` | `GET /api/workspaces` | 🚫 |
| Show detail | `project show` | (list only, no detail view) | 🚫 |
| Update name / description / repository / tags | `project update` | `PATCH /api/workspaces/{id}` route + `updateWorkspace()` API client function both exist, but **no UI ever calls it** — Settings → Workspaces only has create + delete, no edit form | 🚫 |
| Update default branch | `project update --branch` | 🚫 — `UpdateWorkspaceRequest` has no `default_branch` field at all, so this is impossible via the web API regardless of UI | 🚫 |
| Update runtime override | `project update --runtime` | Route supports it, no UI | 🚫 |
| Delete | `project delete` | `DELETE /api/workspaces/{id}`, delete button in Settings | 🚫 |
| Filter tasks/sessions by active workspace | n/a | Yes — `workspace.ts` persists active workspace to localStorage, Overview/Tasks/Board filter by it | 🚫 |

CLI and web are reasonably in sync here (both added/fixed this session).
TUI has no project awareness at all.

---

## 5. Tools

| Capability | CLI | Web | TUI |
|---|---|---|---|
| List built-in tools (12: editor, shell, calculator, think + 8 task tools) | 🚫 | Settings → Tools tab, **and** a separate orphaned `/tools` route (`ToolManager.tsx`) | Tools screen (`t`) |
| Enable / disable a built-in tool | 🚫 | Settings → Tools tab | `t` key |
| Add / edit / delete a custom shell-command tool | 🚫 | Settings → Tools tab | Add: placeholder ("...coming soon..."). Delete: `d` key works. |
| View custom tool detail (`GET /api/tools/{name}`) | 🚫 | Route exists, unused by any frontend code | 🚫 |

**Two separate tool-management UIs exist in the web frontend** —
`Settings.tsx`'s Tools tab (linked in nav) and `views/ToolManager.tsx` at
`/tools` (routed, but **no nav link anywhere** — reachable only by typing
the URL). Worth consolidating into one in the redesign rather than
building a third.

No CLI tool-management commands exist at all — `agent-knots tools ...` is
not a command group. Managing tools is web/TUI only.

---

## 6. Settings / Model Provider

| Capability | CLI | Web | TUI |
|---|---|---|---|
| View current settings | 🚫 (`settings show` is a stub: "Not yet implemented") | `GET /api/settings`, Settings page | 🚫 |
| Edit model/API key/base URL/mode/runtime | Manual YAML edit or env vars only | `PUT /api/settings`, Settings page + first-run Setup Wizard | 🚫 |
| First-run setup wizard | n/a | Yes — auto-triggers when unconfigured, presets for OpenAI/MiniMax/Anthropic/Ollama/custom | 🚫 |
| `default_mode` field | Not documented, not settable via any UI I could find (only via raw YAML edit) | Not exposed in Settings page | 🚫 | Exists on `AgentSettings` but there's no visible field for it anywhere |

The CLI `settings` command group is entirely a stub. All real settings
management is web-only (or manual YAML/env-var editing).

---

## 7. Cockpit shell (auth, layout, navigation)

| Capability | Web |
|---|---|
| Auth | Token-based: cookie, `?token=` query param (for SSE), `Authorization: Bearer` header. Login page + form. |
| Nav (Topbar) | Overview, Board (dropdown), Tasks List (dropdown), Settings. **Tools (`/tools`) is not linked.** |
| Views | Overview (agent cards + new-session), AgentFocus (4 tabs: Terminal/Review/Code/Browser), Board (Kanban), Tasks (list), TaskDetail, Settings (3 tabs: Model Provider/Tools/Workspaces), ToolManager (orphaned) |
| AgentFocus tabs in detail | **Terminal**: real live event stream. **Review**: task detail alongside the agent. **Code**: reconstructs a "files touched" list by **regex-scraping rendered event HTML** rather than structured tool-call data — fragile. **Browser**: pure placeholder UI, no actual dev-server iframe/proxy. |
| Mobile support | 🚫 not implemented (on roadmap) |

TUI has no auth (local-process access only) and no equivalent of
Board/Tasks/Settings/Vault — just Overview → Focus → Tools.

---

## 8. Everything with literally no human-facing UI anywhere

These are real, implemented, working backend capabilities that only an
*agent* can invoke — no CLI command, no web route, no TUI action exists
for a human to trigger them directly:

- **`mark_criterion_met`** — marking acceptance criteria as satisfied.
  Significant now that "done" is hard-gated on this.
- **`add_step`** — adding a step to a task's plan.
- **`delegate_task`** — spawning a sub-agent on a sub-task.
- **`validate_task_output`** — internal validation, not meant to be
  human-triggered, fine as-is.

If the redesign wants humans to be able to do these things too (e.g. a
"mark criterion met" checkbox next to each criterion in TaskDetail), that
needs new backend routes — none exist yet for any of these.

---

## 9. Known GUI bugs worth fixing rather than reproducing in the redesign

- **Kanban board**: only 6 of 8 task statuses have columns; `blocked`/
  `abandoned` tasks vanish from the board.
- **TaskDetail edit form**: description, acceptance criteria, and tags
  edits are all silently dropped by the backend (`UpdateTaskRequest`
  only has title/status/priority/assign). Only title/status/priority
  edits actually persist today.
- **Two tool-management UIs**: `Settings > Tools` and orphaned `/tools`
  (`ToolManager.tsx`), doing the same thing.
- **SSE has no fan-out**: two browser tabs open on the same agent's
  event stream race for events; the second tab silently misses some.
- **Code tab** reconstructs file changes via regex on rendered HTML
  instead of structured tool-call data.
- **Browser tab** is a non-functional placeholder.
- **New Session dialog** only offers Agent/Assistant mode, not
  Reviewer/Security (both real, both CLI-accessible).
- **Create Task dialog** has no acceptance-criteria field (only
  available via post-creation edit, which is itself broken — see above).
- **Workspace editing**: the backend route and frontend API client
  function both exist (`PATCH /api/workspaces/{id}`, `updateWorkspace()`)
  but no UI calls it — Settings → Workspaces only has create + delete.
  Cheap win: the plumbing's already there, just needs a form.

---

## 10. Summary: what a GUI-primary redesign needs to add, not just restyle

If the goal is "GUI primary," these are the real functionality gaps to
close, ranked by how much is currently unreachable without the CLI:

1. **Vault UI** — the whole feature (credentials + templates + audit
   log) has no web presence at all today. Biggest gap.
2. **Fix task editing** — description/criteria/tags edits currently
   silently no-op; needs a backend model fix (`UpdateTaskRequest`) plus
   whatever UI change accompanies the redesign.
3. **A way for humans to mark acceptance criteria met** — currently
   agent-only, and it's now a hard gate on completing a task.
4. **Kanban's missing 2 columns** (blocked, abandoned).
5. **Session send / mode control from a place other than the web** — TUI
   users currently can't chat with or fully control a session; whether
   that's in scope for a *web* redesign depends on how much you still
   care about the TUI going forward.
6. **Reviewer/security mode** exposed somewhere in the session-start flow
   if you want them usable outside the CLI.
7. **Consolidate the duplicate tools UI** rather than carrying both
   forward.
8. **Decide what "Code" and "Browser" tabs should actually be** — both
   are currently fake/fragile placeholders dressed up as features.

Everything else (sessions, tasks CRUD minus the edit-field bug, projects,
tool enable/disable, settings, auth) is real and working — safe to treat
as a given during the redesign, just needs new visual design, not new
backend work.
