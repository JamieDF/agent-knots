# Changelog

All notable changes to agent-knots are documented here.

## [Unreleased]

### Added
- **Playground.** A fresh install is an empty board, with no way to see
  what agent-knots does before committing to setting a workspace up.
  One click now stands up a real half-built project — a colour palette
  generator that was itself built with agent-knots — arriving with the
  genuine tasks that built it: seven done, one waiting on review, three
  never started, each carrying the real progress log from the agent
  that worked it. Offered both in the Dashboard's empty state (where a
  first-timer actually lands) and in Settings (where it can be reset).
  Reset is a full teardown — workspace, tasks and folder — which is
  safe here precisely because it's a demo that can be re-cloned, unlike
  a normal managed workspace.

  The tasks travel inside the repo as `.agent-knots/playground.yaml`,
  written by `agent-knots playground export` and read back on
  workspace creation. Task ids survive verbatim, which is what makes
  the shipped in-review task line up with the branch pushed alongside
  it, since `session_branch_name` hashes the id. Deliberately
  demo-shaped rather than a general "task state travels with the repo"
  feature: tasks are headed for a database that would rewrite the
  format anyway. The source repo is configurable via
  `AGENT_KNOTS_PLAYGROUND_REPO` or a settings field, and defaults to an
  HTTPS URL so it clones without credentials.
- **Managed workspaces.** A workspace can now own its own copy of the
  code. Give it a clone URL or a local path and agent-knots clones into
  `~/agent-knots/workspaces/<repo>/` — outside `~/.agent-knots/` on
  purpose, since it holds your code rather than our state, and
  configurable via `AGENT_KNOTS_WORKSPACES_ROOT`, a Settings field, or
  by following `AGENT_KNOTS_HOME`. Agents work in the clone, so the
  checkout open in your editor is never touched, and they start from a
  clean tree instead of inheriting your uncommitted changes through
  `git checkout -b`. Cloning from a local path adopts that repo's own
  `origin` (demoting the path to a `local` remote) so a later push goes
  upstream rather than back into your working copy. A workspace with no
  repo now gets a real folder too, created once and shared by every
  session in it — previously it fell through to a per-session directory
  under the hidden home, so nothing persisted and two sessions never saw
  the same files. Pointing straight at an existing folder still works
  and is unchanged; the API still defaults to it, so scripts and the CLI
  behave exactly as before, and managed is the default only in the
  create-workspace dialog. `agent-knots project create --managed` does
  the same from the CLI. Deleting a managed workspace keeps the folder
  unless you explicitly ask otherwise — it may hold commits that were
  never pushed. Pushing is its own action
  (`POST /api/workspaces/{id}/push`); approving in Review still only
  commits.

- **DeepSeek provider preset.** Routes through the same OpenAI-compatible
  client every other provider already uses, so no backend changes were
  needed — just a preset (`deepseek-chat`, `https://api.deepseek.com/v1`)
  in the Setup Wizard and Settings' "Add provider" dropdown. Verified
  live end to end: streaming, tool calls, task updates.
- **Workspace-scoped agent tasks.** A workspace-attached session's system
  prompt now tells it which workspace it's in (name, description,
  repository); previously an agent had no way to know at all beyond
  whatever it could infer from files already sitting in its working
  directory. `create_task`, `read_task`, and `list_tasks` are now bound
  to the session's workspace — `project` is closed over, not an
  agent-facing parameter, so a workspace-scoped agent structurally can't
  create, read, or discover (via listing) a task in a different
  workspace, even if told to. `read_task` on a task in another workspace
  returns the same "not found" as a genuinely missing id, so it can't be
  used to confirm another workspace's task even exists.
- **Session history persistence and reopening.** A stopped session's
  full event history now gets written into its wastebin tombstone
  instead of vanishing the moment it stops — `GET /api/agent/{id}` and
  the SSE events endpoint both fall back to it when the session is no
  longer live, so a finished session can be reopened and its full
  transcript replayed read-only, not just while it's running. Task
  Detail has a new "Past sessions" list linking to these.
- **Human-readable session names.** Sessions get an Ubuntu-release-style
  "adjective-animal" name (e.g. "sleepy-panda"), generated at start and
  unique among currently active sessions. Replaces the raw hex session
  id as the primary label everywhere an agent shows up: Dashboard cards,
  the thread header, Task Detail's session blocks and Past Sessions
  list, the notification bell, and the Settings Wastebin list.
- **Live Task Detail polling.** The Task Detail page never polled at
  all — progress an agent wrote while the page was open only showed up
  after a manual reload, unlike the Board/List task views which already
  polled every 5s. Task Detail now does too.
- **Dashboard live activity.** Agent cards show a short summary of the
  agent's most recent action (last message/thinking excerpt, or a
  description of the last tool call), refreshed on the existing 3s
  poll, instead of a bare "working…"/"idle" word with no content.

### Fixed
- **Review hid the agent's actual work, then committed it unseen.**
  `_git_diff_stat` listed only tracked modifications (`git diff
  --numstat`), but approve stages with `git add -A`. So the single most
  common thing an agent does — create a new file — was invisible in
  Review while still being committed by it. Caught by running a real
  agent rather than a fixture: it wrote a new `greet.py`, Review
  reported "no pending changes", and approving would have committed the
  whole deliverable sight-unseen. The same gap swept a stray
  `__pycache__/*.pyc` into an "Approved via Review" commit. Untracked
  files are now listed too, filtered with `--exclude-standard` so the
  set matches exactly what `git add -A` would stage (ignored files
  appear in neither), and `_git_diff_for_file` falls back to a
  `--no-index` diff so their contents actually render.
- **An agent that committed its own work stranded its task in review.**
  The Review screen gated Approve/Reject on there being pending files,
  so a task whose agent committed to the branch itself — leaving
  nothing uncommitted — had both buttons disabled and no way out. Same
  dead end as the non-git case below, reached down the other branch of
  the condition. A task in review can always be actioned now; the API
  already handled it, skipping straight to closing the task out. Only
  the button labels vary.
- **A task in a non-git workspace could enter review and never leave.**
  `_task_repo_and_branch` raised 400 "Not a git repository", so both
  approve and reject failed outright; the task list swallowed that and
  still showed the task, while the UI disabled both buttons because
  there were no pending files to act on. Review is now git-optional
  throughout: with no repo it degrades to reviewing the task itself —
  no diffs, nothing to stage, approve and reject acting on task status.
  The review gate is unaffected, because it was always task logic
  (`set_status` refusing on unmet acceptance criteria) rather than
  anything to do with commits. Rejecting with no files to name also
  stops handing the agent "These files were rejected: ." with an empty
  list.
- **Ten e2e tests had drifted against the UI rebuilds and were failing
  on `main`.** They asserted affordances the redesigns removed or
  moved: the raw task id printed in the List row and Task Detail header
  (both now title-led, with the id in the URL), a `Details →` link and
  stage chips on the Board card (it opens the task on click now, and
  stage moves are drag-and-drop only), a bare `Edit`/`Delete` on Task
  Detail (both moved behind the `⋯ More` kebab, deliberately away from
  Start), "autonomous" on the Dashboard card (it reports run state now;
  Autonomous is a thread-level control), and clicking a Review card
  title to open it (that toggles the diff accordion — `Review files →`
  navigates). One test also clicked the `.ak-card-action` wrapper,
  which is a split control holding both "start and open" and "start
  headless", so the click landed unpredictably and often on the one
  that doesn't navigate. Suite is green: 74 passed, 2 skipped.
- **Chat history lost on navigating away and back.** The backend kept
  only the last 500 raw SSE events per session, but a single tool call
  alone gets re-broadcast on every incremental arg-delta as it streams
  in — confirmed live, one `log_progress` call alone produced 50+ raw
  events — so a real session with a handful of tool calls blew past 500
  within a turn or two, silently evicting the oldest events from the
  ring buffer. Raised the backend cap (500 → 20000) and the frontend's
  rendered-item cap (300 → 3000).
- **Files tab and Command Log tab silently empty for every real
  session.** Every session now gets a sandboxed working directory
  unconditionally, so the tools actually in play are `shell_tool`/
  `editor_tool` (sandbox_tools.py) — but these two tabs (and the new
  "last activity" summary above) were checking for the old plain names
  (`shell`/`editor`) and argument shapes from the richer strands-native
  tools, which no live session's tool calls have matched in a long
  time. Fixed to match reality.
- **Tasks not moving to "in progress."** The existing auto-transition
  only fired when a task's status was already 'open', but a freshly
  created task defaults to 'draft' — the common case of starting an
  agent straight on a new task never visibly showed it as being worked
  on at all. Broadened to fire from draft/open/planned/blocked.
- **A second agent could start on a task already being worked.**
  `POST /api/sessions` now refuses with a clear error if a non-advisory
  session is already active on the given task, instead of two agents
  silently fighting over the same branch and working tree.
- **Task Detail's Start buttons stayed visible even with an agent
  already on the task.** `task.assigned_to` is never cleared when a
  session stops, so it was already unreliable as a liveness signal.
  Switched to the page's own live-fetched agent list, and the resulting
  "Watch" button now names the actual agent doing (or who did) the
  work instead of generic text.
- **Dashboard agent cards overflowing their workspace container.** A
  fixed `1fr 1fr` grid plus a plain-div `Card` with no min-width/
  overflow handling meant a long unbroken string (a file path or shell
  command in the new "last activity" summary) forced the grid track
  wider instead of respecting its ellipsis truncation. Switched to a
  responsive `auto-fit` grid with a min/max card size and fixed the
  min-width trap at both the grid-item and inner flex-row level.
  Verified with real screenshots at 1280px and 700px.
- **Taskless session picking up a task didn't update the goal rail.**
  A session started with no task now adopts the first task it creates
  or logs progress/status on, the same as one started with a task from
  the outset.
- **Review, redesigned around tasks instead of raw git diffs.** The
  Review screen used to be a flat, task-agnostic list of every
  workspace's uncommitted changes — no connection at all to a task's
  own "review" status, despite sharing the name. It's now a list of
  tasks actually sitting in review; clicking one shows the task's own
  details alongside its file changes, with per-file or all-at-once
  approve/reject. Reject opens a dialog for a reason and sends it back
  to the agent — see the pause/resume behavior below for how.
- **Tasks entering review now pause their session instead of stopping
  it.** A task reaching `review` used to auto-stop every session
  working it, losing the whole conversation — reopening it later meant
  starting fresh with no memory of what was actually discussed.
  `review` now pauses (interrupts the current turn, switches to
  assistant mode — the same mechanism the Autonomous toggle already
  used) rather than stopping, so Review's reject flow can resume the
  *exact same thread* with the reviewer's feedback instead of losing
  all context. Verified live end to end: paused → rejected with a
  reason → same session resumed and fixed it → re-entered review →
  paused again → approved → committed, task moved to done, and *now*
  the session actually stops (real work is done, not just paused).
  `done`/`abandoned` still stop for real, as before.
- **Loading spinner.** No screen ever indicated it was still loading —
  an empty list and a not-yet-loaded list looked identical. Added a
  `Spinner` primitive, shown on Task Detail's initial load and on the
  Tasks Board/List views until their first fetch settles (not on every
  background poll after that, so it doesn't flash over content that's
  already there).

### Fixed
- **Wastebin reads were parsing full session transcripts just to list
  entries, making Task Detail (and the Review task list, and the
  Settings Wastebin card) noticeably slow.** Every wastebin read
  parsed the *entire* stored history — up to tens of thousands of
  events — even when the caller only needed small metadata fields.
  Measured against real data: one `list()` call took 4.58 seconds with
  a 2.3MB history file on disk. History now lives in a separate file
  from the metadata YAML, only read when a session is actually being
  reopened; existing large files self-migrate (split apart, once) on
  their first read after upgrading. Post-migration: 0.014 seconds for
  the same call.
- **Task Detail showed the Start buttons for a beat before flipping to
  "Watch X," every time.** The task and its live agents were fetched
  as two separate sequential calls, so the page rendered before the
  agents call had resolved. Fetched together now — the correct button
  shows from the very first paint, no flash.
- **Button/chip styling inconsistencies on Task Detail.** A handful of
  buttons on this one screen used one-off padding/font-size values with
  no reason behind them (e.g. one button at `padding: '6px 16px'` while
  every other primary button on the page used `5px 12px`). Normalized
  to match the rest of the screen; also dropped a couple of redundant
  inline resets that just duplicated the global button CSS.

## [0.2.0] - 2026-07-28

### Fixed
- **Agent Thread: stale thread state on navigating between sessions.**
  Starting a new session while already viewing one (or otherwise
  navigating from `/agent/A` to `/agent/B`) hit the same route element
  without remounting, so the previous session's events/agent/task
  state sat there until new data replaced it — looking like the new
  session hadn't opened. `AgentThread` is now keyed by the session id
  at the route level, forcing a clean remount on every session switch.
- **Agent Thread: delete session had no confirmation or tooltip.** The
  "✕" next to "■ Stop" permanently deleted the session immediately on
  click — same destructive action as Stop's neighbor with no warning
  and no indication of what it did. Added a `title` tooltip and a
  confirm prompt before deleting.

### Added
- **Agent Thread: real chat layout, markdown rendering, dedup fix.**
  Agent and user turns now anchor like a real chat — agent left, user
  right — instead of both sitting in the same left-aligned column with
  a letter-avatar circle (removed the "A"/"Y" avatars entirely; just
  alignment + a timestamp now). Message/thinking/blocker text is
  rendered as markdown (`react-markdown` + `remark-gfm`) instead of raw
  text, so bold, lists, links, tables, and code blocks actually render
  instead of showing literal asterisks/backticks — this was the biggest
  part of "formatting is kinda fucked up," since a multi-line response
  wasn't even wrapping on `\n` before (no `white-space: pre-wrap`, and
  no markdown parsing at all). Also fixed the code-block renderer
  picking up `index.css`'s global `code { background; padding }` rule
  meant for small inline snippets elsewhere in the app — without an
  explicit override it left ugly per-line highlight boxes behind block
  code, worst in dark theme. Separately fixed a real backend bug: every
  turn's "Agent finished." line was appearing twice — `_chunk_to_event`
  was turning the stream's own `result` chunk into a second
  `STATE_CHANGE` event even though `_run_agent` already broadcasts its
  own "Agent finished." right after the stream loop ends normally; the
  chunk case now emits nothing.

  **Follow-up in the same area, found from a real transcript**: none of
  the above was enough on its own, because the backend was still
  emitting one `Event` per raw text delta (often a handful of words
  each) and the frontend rendered every single one as its own bubble.
  Concretely that: (1) split markdown across bubble boundaries, so a
  `**bold**` run or a `- ` list starting in one delta and finishing in
  the next rendered as literal asterisks/dashes; (2) left real reply
  text stranded inside a collapsed "thinking" bubble whenever a single
  delta happened to contain both the `</think>` close tag and the
  start of the actual answer in the same fragment — the old code
  classified the *whole* fragment as one type based on state from
  before that delta, so text after the tag got mislabeled as thinking;
  (3) re-emitted the turn's full text a second time as one final
  duplicate chunk once streaming finished. Fixed on both ends:
  `_chunk_to_event` (`session/manager.py`) now splits a single delta at
  every `<think>`/`</think>` boundary it contains instead of picking
  one type for the whole fragment, tracks whether anything was
  actually streamed this turn, and skips the final full-text chunk
  when it would just duplicate what was already streamed (only sent
  when a provider doesn't stream at all). The frontend now accumulates
  consecutive same-type message/thinking events into one growing
  bubble instead of appending a new bubble per delta, so markdown
  finally renders against the complete text.
- **Agent Thread: full-width unattached sessions, framed panel.** A
  session with no task attached still rendered the 260px goal rail as
  an empty "No task attached to this session" column — now the rail is
  skipped entirely for unattached sessions and the center thread takes
  the full width. The whole thread panel (header + 3 zones) is now
  wrapped in a rounded, bordered card with a small margin and shadow —
  matching the floating-card look used everywhere else in the app —
  instead of sitting flush edge-to-edge against the window.
- **Settings side nav + Vault folded in.** Settings has grown to eight
  cards, long enough that finding one meant scrolling by hand — added
  a sticky side nav (`Usage · Model providers · Tools · Policies ·
  MCP servers · Integrations · Vault · Workspaces`) that jumps to and
  highlights the current section as you scroll. Vault (locked/unlocked
  state, credentials, audit log) was previously its own top-nav screen;
  it's just more config, so it's now a Settings section instead — the
  old `/vault` route redirects to `/settings#vault` for old links/
  bookmarks. Landing on a section via hash needed a few retries over
  ~1s rather than one scroll-on-mount: every card fetches its own data,
  so the page keeps growing taller for a beat after first paint and a
  single early scroll gets shoved out from under itself. Also needed
  generous bottom padding after the last section — without it, a short
  trailing section (Vault, Workspaces) can never be scrolled flush to
  the top since there isn't enough content below it to push it there,
  which left the nav's active-highlight visibly stuck on an earlier
  section whenever you jumped to one.
- **Kanban drag-and-drop.** Task cards on the Board can now be dragged
  between columns to change status, alongside the existing click-to-
  expand-then-click-a-stage-button flow (kept as-is, not replaced).
- **Nicer workspace switcher.** The topbar's workspace scope picker is
  now a proper dropdown (`WorkspaceSwitcher.tsx`) matching the rest of
  the design, instead of a bare native `<select>`.
- **Create-workspace flow from the Dashboard.** A "No workspaces yet"
  prompt now offers "+ Create workspace" whenever there are none,
  instead of only "+ New session" with no way to actually add a
  workspace from the Dashboard at all. The create/edit dialog (now
  shared between the Dashboard and Settings, `WorkspaceDialog.tsx`)
  drops the id field entirely — the backend slugifies one from the
  name and dedupes collisions (`POST /api/workspaces`'s `id` is now
  optional) — and replaces the free-text repository path with a
  server-assisted folder browser (`GET /api/fs/browse`, new
  `FolderPicker.tsx`), since a native OS file dialog can't hand back an
  absolute path a local backend process can use. Once a folder is
  chosen, `GET /api/fs/git-info` detects whether it's a git repo with a
  GitHub remote (SSH, `ssh://`, and HTTPS remote URL forms) and shows a
  clickable `github.com/owner/repo` link right in the dialog.
- **Atelier cockpit redesign — Phase 0 (foundations) + Phase 1 (Tasks/
  Board core).** Full frontend rebuild described in
  `design_handoff_atelier_cockpit/`.
  - *Phase 0*: light/dark theme system with persisted toggle, reactive
    URL-synced workspace scope (no more full-page reload to switch
    workspaces), a shared primitives library (Card/Chip/Toggle/
    StatusDot/PriorityLabel/SectionLabel/Dialog/Mono), BrowserRouter
    with a proper SPA-fallback route for deep links (was HashRouter).
    SSE rewritten end to end: the backend now streams structured JSON
    events (`events.py::serialize_event()`) instead of pre-rendered
    HTML fragments, and multiple simultaneous viewers of one agent
    (e.g. two browser tabs) each get their own event queue instead of
    racing for a single shared one. Six new event kinds (`auto_log`,
    `steer`, `delegate`, `checkpoint`, `user`, `ended`).
  - *Phase 1*: Tasks screen with Board/List tabs (stage-driven columns,
    expand-in-place cards, stage filter chips), a unified task create/
    edit dialog (chip tags, criteria/steps row-list editors, review-gate
    select, "✨ Draft with agent"), and a rebuilt Task Detail (lifecycle
    strip, real clickable acceptance criteria, session/tools-used/
    related-tasks side blocks). Task API gained `review_gate`,
    per-criterion toggling, single-agent detail, and an agent-assisted
    task-drafting endpoint.
  - *Phase 2*: Dashboard rebuilt as one workspace cluster per workspace
    (plus an "Unassigned" bucket), each with a blocker hero (question/
    suggested-answer buttons/reply, sourced from the blocked task's own
    progress log), a 2-up grid of active-session cards, an "up next"
    queue with Start, pipeline-stage counts, and a per-workspace
    auto-assign toggle. A real "New session" dialog
    (attach-to-task/prompt/mode/workspace) replaces both the disabled
    Topbar placeholder from Phase 0 and the old ad-hoc inline
    task-picker. `Project` gained config-only `auto_assign`/
    `max_concurrent` fields (no scheduler enforces them yet).
  - *Phase 3*: Agent Thread fully rebuilt — three-zone layout with a
    collapsible goal rail (⌘B), a renderer for every event kind
    (message, collapsible thinking, merged tool call+result, auto-log,
    steering nudge, delegation cards that expand via their own nested
    SSE subscription to the sub-session, checkpoint+revert, blocker
    ask, user reply, session end), driving/watching-locked/ended
    composer states, a replay scrubber, and Terminal/Files/Preview
    right-rail tabs. New checkpoint/revert endpoints (broadcast-only,
    matching the design prototype's own no-op mock behavior). Verified
    against a real MiniMax M2.7 call, not just a fake test key.
  - *Phase 4*: Workflows screen (board-stage toggles, a Planner/Builder/
    Reviewer role registry with a model/trigger/prompt/tools config
    dialog, a generated workflow diagram, pipeline-template shortcuts)
    and a Review screen (pending diffs derived live from each
    workspace's git status, expand-to-view-diff, approve/reject/
    approve-all). New `workflows/` backend module (`Stage`/`Role`/
    `Trigger` models, YAML-backed `StagesStore`/`RolesStore`) and
    `_maybe_fire_role_triggers()`, which starts an enabled role's agent
    session when a task's status crosses a configured stage boundary
    (`leaves_draft`/`is_started`/`enters_review`) via the task-update
    API — not yet wired to agent-tool-driven status changes, and every
    role ships disabled by default since firing one spends real API
    money. Review approve/reject is git-backed (`git add`+`git commit`
    per file or whole workspace); reject deliberately never discards —
    it only acknowledges, matching the project's stance of never
    automating destructive git operations.
  - *Phase 5*: Vault screen (locked/unlocked card states, credential
    list + add + delete, injection-template chips, audit log — new web
    routes over the existing, unmodified `VaultStore`; credential
    values never appear in a list/get response) and a rebuilt Settings
    screen (Usage card backed by a new append-only JSONL usage ledger,
    named Model-provider profiles with "Set default", consolidated
    Tools, Policies, MCP server registry, Integrations, and Workspaces
    CRUD). New `usage.py`, `policies/` (`PolicyStore`), `mcp_servers.py`
    (`McpServerStore`) backend modules; `Settings` gained `providers`,
    `default_provider`, and `integrations`, additively — `agent.*`
    still holds the one config `resolve_provider()` actually reads, and
    "Set default" just copies a saved profile into it, so the Phase 3
    env-var-precedence fix stays untouched. The daily spend-cap policy
    is the only one with real enforcement — `POST /api/sessions` checks
    today's ledger total and blocks with a 400 once the configured cap
    is reached; the other three policies (migrations guard, pause-
    after-test-failures, no-sudo) are configurable but not yet enforced,
    same as MCP servers (registry only, no client) and Integrations
    (GitHub PR-on-review / phone-push toggles, both config-only — no
    OAuth flow or push infra exists).
  - *Phase 6*: Setup wizard restyled to the real design (logo tile,
    preset chips, plain-YAML warning, Skip / Finish setup →) — it was
    already auto-shown whenever `/api/settings` reports unconfigured,
    since Phase 0/2; this phase just gave it the real look and fixed a
    stale-default prefill bug (see Fixed). Login page (still
    server-rendered, deliberately, per the Phase 0 decision that it
    must work before any JS bundle exists) restyled to the real Atelier
    tokens in both themes, reading the same `agent-knots-theme`
    localStorage key the rest of the app uses via one small inline
    script. A real notification bell replacing the static placeholder —
    badge count is pending blockers specifically, dropdown covers
    blocker + recently-done tasks with deep links, footer toggle wired
    to the real `phone_push` setting from Phase 5. Derived by polling
    the same tasks list the Dashboard already polls rather than a live
    SSE subscription across every active session — a disclosed,
    deliberate scope call, not an oversight.

### Fixed
- **Settings screen couldn't be scrolled past the fold.** `.canvas`
  (the flex child wrapping every routed view in `App.tsx`) had
  `overflow: hidden` but no `display: flex`, so `DeskLayout`'s own
  `flex: 1; overflow-y: auto` never got a bounded height to scroll
  within — it just rendered as a plain block sized to its content, and
  anything past the viewport was clipped instead of scrollable. Fixed
  by making `.canvas` a flex container (`display: flex; min-height: 0`)
  so its child actually participates in the flex layout.
- **No way to archive or delete a workspace.** `Project` gained an
  `archived: bool` field (persisted, toggled via the existing
  `PATCH /api/workspaces/{id}` route); `GET /api/workspaces` hides
  archived workspaces by default (so the topbar scope switcher and
  Dashboard never offer one) but Settings' management view requests
  `?include_archived=true` and renders active/archived as separate
  groups with Archive/Unarchive actions. Deleting a workspace (which
  already worked server-side) had no confirmation at all — added a
  browser confirm dialog before the DELETE call, since it's
  irreversible.
- **No way to get from a task to its agent's thread.** Task Detail's
  header showed a static "● Agent active" label with no click handler
  at all once a session was assigned, and the Session side-block
  (mode/tokens/cost) had no link either — there was genuinely no path
  from a task back to the conversation working on it. Both now
  navigate to `/agent/{assigned_to}`. Verified the full lifecycle end
  to end while fixing this: create (lands in draft) → open → start
  agent → in_progress → blocked from skipping straight to done →
  review → done, plus the `review_gate: auto` "Run review now" button's
  refuse-then-succeed path once unmet criteria are marked met.
- **A task created while scoped to a workspace wasn't saved to it.**
  `TaskDialog`'s create path never read the current workspace scope at
  all, so every new task's `project` came back empty regardless of
  which workspace the Tasks screen was scoped to when you clicked "+
  New task" — it just silently landed unassigned. Fixed by reading
  `useWorkspaceScope()` and passing it through as `project` on create.
- **Workspace scope was silently dropped on every in-app navigation.**
  `WorkspaceProvider` derived the current scope live from the `?ws=`
  URL param, but a plain `<Link>`/`<NavLink>` to another route carries
  no query string at all, and the provider only mounts once for the
  whole app — so there was nothing left to re-seed the scope from after
  the first load. Picking a workspace then clicking any nav link reset
  it back to "All workspaces" immediately. Fixed by keeping the scope
  as its own React state (initialized from the URL or localStorage,
  whichever's set), with the URL kept in sync on top of it rather than
  being the source of truth.
- **A session started via a bare "Start" button on a task never
  actually began running.** `SessionManager.start()` only kicks off the
  agent's first turn when `task_description` (the literal prompt text)
  is non-empty — every "Start" action across the Dashboard, Task
  Detail, and Board starts a session with an empty prompt on purpose
  (the task's full context is already baked into the system prompt
  instead). The agent mode session just sat idle, looking dead, until
  something else happened to trigger a turn (e.g. assuming control and
  typing a message). Fixed by falling back to a generic kickoff message
  when a task is attached but no explicit prompt was given.
- **Tasks could skip straight from in_progress to done, bypassing
  review entirely.** `_validate_transition()` only checked acceptance
  criteria for the done gate — a task with none at all (or all of them
  met) could go straight to done from any status. Now a task with
  `review_gate` other than `none` must already be in `review` status
  before it can be marked done; `PATCH /api/tasks/{id}` also now wraps
  this in a clean 400 instead of letting the store's `ValueError`
  propagate as a bare 500.
- **New tasks started in Open, not Draft.** Per the intended workflow
  (draft → open → in_progress → review → done), a task should sit in
  Draft until someone deliberately takes it out. Fixed by changing both
  the `Task` dataclass default and `CreateTaskRequest`'s default to
  `draft`; the CLI, agent-callable `create_task` tool, and web API all
  picked this up automatically since none of them passed an explicit
  status. Also fixed a role-trigger bug this exposed: a task can now
  jump straight from draft to in_progress in one hop (skipping Open),
  which used to fire only the `leaves_draft` trigger or only the
  `is_started` one (an if/elif chain) instead of both.
- **The Tasks screen header's "+ New task" dialog didn't refresh the
  board/list.** It closed the dialog but never told whichever view was
  showing to reload, so a new task only appeared after the next 5s poll
  tick or a manual page refresh. Fixed with a reload-signal prop passed
  down from the shared `Tasks.tsx` shell.
- **"✨ Draft with agent" could fail against MiniMax and other
  OpenAI-*compatible* (not literally OpenAI) providers.** It passed
  `response_format={"type": "json_object"}`, an OpenAI-specific
  strict-JSON-mode parameter not every compatible provider implements —
  an unsupported param 400s the whole completion instead of just
  degrading gracefully. Fixed by dropping it and parsing the completion
  text leniently instead (tolerates markdown code fences and stray
  commentary around the JSON). That lenient parse then surfaced a
  second bug: MiniMax M2.7 is a reasoning model that inlines its
  `<think>...</think>` block directly into a plain completion's
  `message.content` (there's no separate reasoning field to skip), and
  since a coding-task "think" block routinely contains its own literal
  `{`/`}` characters, a naive "first `{` to last `}`" scan could grab
  braces from *inside* the reasoning instead of the real JSON object —
  producing text that wasn't valid JSON at all and surfacing a raw,
  uninformative `json.JSONDecodeError` ("Expecting value: line 1 column
  1 (char 0)") instead of a clear error. Fixed by stripping any
  `<think>` block before parsing, and by making the fallback brace-scan
  itself exception-safe with an actionable error message instead of
  letting a decode error bubble up raw.
- **The Agent Thread's page itself could scroll instead of just its
  event stream.** `#root`/`body` used `min-height: 100vh`, which lets
  them grow past the viewport on a tall page instead of clipping at it
  — so `.canvas`'s `flex: 1; overflow: hidden` had nothing determinate
  to clip against, and the whole page scrolled. Fixed with a fixed
  `height: 100%` (and `overflow: hidden` on body) so the header, goal
  rail, and composer stay fixed in place and only the event stream
  itself scrolls, matching every other screen's `DeskLayout` scroll
  behavior.
- **`PATCH /api/tasks/{id}` silently dropped description/tags/
  acceptance_criteria/steps edits.** `UpdateTaskRequest` was missing
  those fields entirely; the frontend's edit dialog sent them but
  nothing on the backend ever applied them. Fixed with existing-entry
  matching so criteria_met/step status survive an edit that doesn't
  touch them.
- **Task API responses omitted `criteria_met` entirely.** Only
  `acceptance_criteria` (the full list) was ever returned, so the
  frontend had no way to know which criteria were already met on page
  load — every criterion looked unmet until toggled again this session.
- **Dashboard only showed sessions with `running===true` at that exact
  instant**, hiding idle-between-turns or assistant-mode-waiting
  sessions entirely — found via Playwright, not just a cosmetic gap
  (there was no way to click back into an idle session from the
  Dashboard at all).
- **`POST /api/sessions` ignored env-var configuration for the actual
  session**, only for the pre-flight "configured" check. It passed
  `settings.load()`'s file values straight through as override args,
  which always outranks env vars in `resolve_provider()`'s precedence —
  a user configured entirely via `AGENT_KNOTS_*` env vars (the
  documented zero-touch install path) would see `configured: true` in
  the UI but every session would silently build against the wrong
  model. Found by testing against a real MiniMax M2.7 key.
- **`<think>...</think>` reasoning tags commonly split across multiple
  stream deltas were misclassified.** The per-fragment heuristic had no
  memory of an already-open think block, so most of a multi-fragment
  thinking block leaked through as plain assistant-message text, tag
  literals included. Now stateful across chunks, with tags stripped.
- **Streamed tool-call args re-emit the same event as they accumulate**
  (empty → partial → complete) — rendered as 2-3 duplicate tool cards
  until the frontend started updating the existing card by id instead
  of appending a new one per update.
- **Assume/Relinquish looked unresponsive** for up to one 3s poll cycle
  (mode chip/composer only updated on the next background poll) — now
  applies optimistically on click.
- **The `openai/`-prefixed model-id convention doesn't work.**
  `OpenAIModel` sends `model_id` as-is with no prefix-stripping, and
  `litellm` (which would understand `provider/model` routing) is a
  listed dependency never actually imported anywhere. Fixed the
  MiniMax-specific docs (`provider.py`, `docs/quickstart.md`), which
  were fully confirmed broken against a real call; the same issue likely
  affects the default OpenAI preset and 2 of the other 3 Setup Wizard
  presets but needs its own dedicated look rather than a rushed fix here.
- **`StagesStore`/`RolesStore` returned shared mutable defaults.**
  `list()` did a shallow `list(DEFAULT_STAGES)`/`list(DEFAULT_ROLES)`,
  which copies the list but not its `Stage`/`Role` elements — `update()`/
  `toggle()` mutating a returned object corrupted the shared
  module-level defaults for the rest of the process. Caught by a real
  pytest cross-test contamination failure. Fixed with `copy.deepcopy()`.
- **`POST /api/review/approve` didn't check `git add`/`git commit`'s
  exit code.** A failing commit still returned `{"status":
  "committed"}` to the client. Caught by a Playwright test expecting a
  second commit that never landed. Now raises a 500 with the captured
  stderr if either command fails.
- **A test for the new "Set default" provider action left `agent.api_key`
  set to a fake test key with no way to undo it**, since `DELETE
  /api/settings/providers/{name}` only removes the saved profile, not
  an already-applied default, and `PUT /api/settings` deliberately
  treats an empty `api_key` as "leave unchanged" (so a blank PUT can't
  accidentally wipe a real key). Fixed in the test by reading and
  restoring the raw `settings.yaml` directly, rather than adding a new
  API-level way to blank a key that isn't needed anywhere else yet.
- **The Setup Wizard could show the MiniMax preset chip selected while
  the Model ID field silently held a stale `openai/gpt-4o-mini`.**
  `AgentSettings.default_model` has a non-empty dataclass default even
  on a totally fresh install, and the wizard's prefill effect trusted
  it unconditionally. Fixed by only prefilling from existing settings
  when `base_url` or `api_key` is actually non-empty — both correctly
  default to `""`, unlike `default_model`.

- **`install.sh`.** One script, run after `git clone`: installs `uv` if
  missing, `uv sync`s Python dependencies, builds the web cockpit
  frontend (skipped with a clear warning if Node isn't available), and
  installs the `agent-knots` command globally via `uv tool install`.
  Idempotent — safe to re-run.
- **Acceptance-criteria enforcement.** `Task.criteria_met` tracks which
  acceptance criteria have been explicitly marked satisfied via the new
  `mark_criterion_met` task tool/CLI. `TaskStore` now refuses a transition
  to `done` (via `set_status` or a status-carrying `log_progress` call)
  until every criterion is marked met. Previously nothing enforced this —
  an agent could mark a task done with unmet criteria and nothing stopped
  it.
- **Real resource limits on shell/custom-tool execution.**
  `sandbox_tools.run_confined()` applies CPU/memory limits and kills the
  whole process group (not just the direct child) on timeout, fixing
  orphaned background processes that the old `subprocess.run(timeout=...)`
  could leave behind. This is not a full security sandbox — see
  `sandbox_tools.py`'s module docstring for what it does and doesn't
  cover.
- Tests for `SessionManager.start()` and `session/runtime.py`, both
  previously at zero coverage (31 new tests total this session).
- **CLI: `project` subcommand group.** `create`, `list`, `show`, `update`,
  `delete` now wired to the existing `ProjectStore` (previously only
  `project list` existed, and only as a stub — the web cockpit already
  had full CRUD via `/api/workspaces`).
- **CLI: `vault template` subcommand group.** `add`, `list`, `show`,
  `remove` for managing per-credential injection templates (`--env`,
  `--file`, `--stdin`, `--wrapper`), matching the `VaultStore` methods
  that already backed the data model. Actually *using* a template to
  inject a credential into a spawned command (an agent-callable
  `vault_use` tool) is still not implemented — see roadmap.

### Fixed
- **`delegate_task` (multi-agent delegation) now actually reaches the
  agent.** It was being appended to the tool list *after* the Strands
  `Agent` was already constructed with the earlier list, so the tool
  almost certainly never registered.
- **`InProcessRuntime` was dead code.** `SessionManager.start()` never
  constructed it and ran the agent loop directly instead, bypassing the
  `SessionRuntime` abstraction. It's now wired through `create_runtime()`
  like the subprocess path. Fixing this also surfaced and fixed a related
  bug: `create_runtime()` ignored an explicitly resolved runtime type
  (e.g. a per-project override) in favor of a possibly-stale global
  setting.
- **Disabling a built-in tool actually disables it now.**
  `ToolRegistry.list_builtin()`/`list_enabled()` hardcoded every built-in
  as enabled and never read the disabled-tools file — toggling one off
  (from the web Settings page or TUI) persisted the change but had zero
  effect on which tools an agent actually got.
- **Custom tools now run in the session's workspace, not the server's own
  cwd.** They previously ran via `subprocess.run()` with no `cwd` set at
  all, silently ignoring whatever workspace was configured.
- **Auth token comparisons are constant-time again.** `server.py`'s
  middleware and `/login` were comparing tokens with plain `==`/`!=`
  instead of `auth.py`'s `verify_token()` (which exists specifically to
  avoid timing attacks) — the helper was there, just unused. Consolidated
  onto one implementation and added `Authorization: Bearer` support to
  the actual middleware (previously only the dead `Auth.require()` had
  it). Also fixed `Auth.cockpit_url`, which was a `@property` that
  couldn't accept the `host`/`port` arguments it declared.
- **`WorkspaceSandbox.max_output`/`max_file_size` are enforced now.**
  Shell output is truncated past `max_output`; editor writes past
  `max_file_size` are rejected before touching disk. Both fields existed
  but were never read by anything. `allowed_urls` was removed instead of
  enforced — no tool exists for it to gate, and the shell tool's
  unrestricted network access would have made a URL allowlist on some
  future tool meaningless anyway.
- **The GUI setup wizard now honors `AGENT_KNOTS_*` env vars, not just
  the settings file.** `GET/PUT /api/settings`'s `configured` flag and
  `POST /api/sessions`'s pre-flight check both used to call
  `settings.is_configured()`, which only looks at
  `~/.agent-knots/settings.yaml`. A user configured entirely via env vars
  (common for containers/CI) would see the wizard every time and
  literally could not start a session from the web GUI — the 400 fired
  before `SessionManager.start()` ever got a chance to resolve the env
  vars itself. Both now use `provider.resolve_provider().is_configured`,
  matching the CLI's actual precedence (flags → env vars → file).
- **The setup wizard no longer claims your API key is "stored
  encrypted."** It's plain-text YAML in `settings.yaml` — only the vault
  encrypts anything. Fixed the copy to say so and point at the vault for
  actual encrypted storage.

### Removed
- **`save_checkpoint`/`load_checkpoint`.** Implemented but never called
  from anywhere (no CLI command, no API route). `inject_memory` already
  covers cross-session continuity via the task's progress log; real
  session/agent-state resume would need to serialize actual conversation
  history, which is a real feature to design later, not something worth
  half-wiring up as-is. See `docs/strands-features.md`.
- **`Auth.require()`.** Assumed a per-route `Depends()` architecture the
  app doesn't use, so it was a second, unreachable auth implementation
  rather than a real option — see the auth fix above.

Tests: 106 → 171 this session (65 new), including first-ever coverage for
`sandbox_tools.py`, `session/runtime.py`, `SessionManager.start()`, task
tool validation, and authenticated web requests — all previously at zero.

### Changed
- **Renamed project from "AgentJam" to "agent-knots".** Python package is
  now `agent_knots` (import path), CLI binary is `agent-knots`. Default
  data directory is now `~/.agent-knots/`. Legacy Go implementation
  (`cmd/`, `internal/`, `go.mod`) removed — superseded by the Python
  rebuild below.

### Added
- **Python rebuild** — Complete rewrite from Go to Python on Strands Agents SDK
- **Web cockpit** — Vite + React SPA with agent cards, Kanban board, task detail, settings
- **TUI cockpit** — Textual TUI with agent list, focus view, tools manager, keyboard shortcuts
- **Task system** — YAML-backed tasks with progress logs, steps, acceptance criteria
- **Kanban board** — 6-column board with status chips, priority indicators
- **Vault** — AES-256-GCM encrypted credential store (ported from Go)
- **Agent tools** — 11 built-in: editor, shell, calculator, think + 7 task tools
- **Custom tools** — User-defined shell command tools via settings
- **Workspaces** — Multi-project grouping with task/agent filtering, path isolation
- **Runtime modes** — In-process (fast) + subprocess (isolated), per workspace/session
- **Assume/Relinquish** — Mode switching with tool gating via Strands Interventions
- **Multi-turn chat** — Sequential conversation with context retention
- **Agent panels** — Terminal, Review, Code, Browser tabs in focus view
- **Memory** — Cross-session progress injection into system prompt
- **Multi-agent** — `delegate_task` tool for spawning sub-agents
- **Checkpoint** — Session state save/load for pause/resume
- **Steering** — Tool outputs validated against task acceptance criteria
- **Structured output** — Task data validation (title, status, priority)
- **Real token tracking** — Model call hooks report actual token usage + cost
- **Auto progress logging** — Tool calls auto-log to task progress

### Tests
- 106 Python unit tests (vault, session, task, web)
- 43 Playwright e2e tests (cockpit flow, task CRUD, board, settings, panels, runtime)

- **Per-session subprocess management.** `session start --detach` forks a
  child process (`agentjam session run <id>`) that holds the driver alive,
  serves events on a UNIX socket, and writes PID/sock/log files.
- **Live event streaming protocol.** Each session exposes a UNIX socket
  (`~/.agentjam/sessions/<id>.sock`) that broadcasts JSON-encoded events
  to any connected client. `session logs <id>` follows the stream.
- **Bidirectional control channel.** The same socket accepts control
  messages (set-mode, send) from clients, enabling assume/relinquish and
  message injection from any UI surface.
- **Session discovery.** `live.List()` scans the sessions directory for
  live PID files, verifies process liveness, and cleans up stale entries.

### Added — Drivers

- **Mock driver** (`internal/agent/driver/mock`). 364 LOC. Emits scripted
  agent events (thinking, tool calls, messages, mode changes) on a timer.
  Supports SetMode/Send for testing take-over flow. Used by all demos
  and integration tests.

### Added — Take-over Flow

- **Assume/relinquish control.** Mode swap between `agent` and `assistant`.
  Implemented across three surfaces:
  - CLI: `session assume <id>`, `session relinquish <id>`, `session send <id> <msg>`
  - TUI: `a` key (assume), `r` key (relinquish)
  - Web: POST endpoints + action buttons
- The control channel delivers mode-swap commands to the session
  subprocess, which calls `driver.SetMode()` and emits a state-change event.

### Added — Git Worktree Integration

- **`--worktree` flag** on `session start`. Creates a real git worktree
  at `.agentjam/worktrees/<session-id>/` with a branch named
  `agent-<session-id>`. Worktree is removed and branch deleted on stop.
- `internal/vcs/git.go` (192 LOC): CreateWorktree, RemoveWorktree,
  DeleteBranch, Cleanup, IsGitRepo — all via `git` shell-outs.

### Added — Egress Filtering

- **iptables DROP rules** in the container's network namespace for 12
  CIDR ranges (RFC1918, link-local, loopback, cloud metadata endpoints).
  Installed via `podman unshare nsenter -t <PID> -n iptables -A OUTPUT`.
- `internal/container/egress.go` (109 LOC): InstallEgressRules,
  VerifyEgressRules. Non-fatal on failure (logged, not fatal).
- 4 egress unit tests + integration verification.

### Added — TUI Cockpit (v0.3)

- **Bubble Tea TUI** with two views: agent list and per-agent focus.
  - Agent list: live status, mode, uptime, tokens, current action.
    j/k to navigate, Enter to focus.
  - Focus view: real-time event stream from the session's event socket.
    a/r to assume/relinquish, p to pause, Esc to go back.
- `liveRegistry` caches `liveDriver` instances by session ID to avoid
  duplicate socket connections on every poll tick.
- `streaming` flag prevents goroutine accumulation from re-issuing
  `watchEvents` on every 2-second tick.

### Added — Web Cockpit (v0.4)

- **Browser-accessible cockpit** at `127.0.0.1:<random-port>`.
  - Token auth: 64-hex-char token generated on first start, saved to
    `~/.agentjam/cockpit.token` (mode 0600). Cookie-based after first
    login. `?token=` query param for one-click CLI integration.
  - Agent list page: vanilla JS `fetch()` polling every 2 seconds.
    Agent cards with status, mode, uptime, tokens, cost.
  - Agent detail page: SSE event stream via `EventSource`. Each browser
    tab gets its own event socket connection (no sharing issues).
  - Control actions: Assume, Relinquish, Send message (POST endpoints).
  - Fully self-contained: inline CSS, no CDN dependencies.
- `internal/cockpit/web/` package (671 LOC): server.go, handlers.go,
  sse.go, templates.go.

### Added — Testing

- **Integration test suite** (`internal/integration/`, 651 LOC, 10 tests).
  Build-tagged (`//go:build integration`). Exercises the full lifecycle:
  session start → event streaming → control channel → worktree → stop.
  Run with: `go test -tags integration ./internal/integration/...`
- **Smoke test script** (`scripts/smoke.sh`, 13 checks). Bash end-to-end
  covering lifecycle, events, takeover, worktree. All passing.

### Added — Podman Fixes

- Rootless podman 5.8.2 verified working. Network mode `"private"` → `""`
  (pasta creates isolated netns). `--storage-opt` disabled by default
  (only works on XFS+overlay). `--userns keep-id` confirmed working.

### Fixed

- **Duplicate events in cockpit TUI.** Registry created new `liveDriver`
  (new socket connection) on every 2-second tick. Event server broadcasts
  to all connected clients → fan-out amplification. Fixed by caching
  `liveDriver` instances by session ID + tracking streaming state.
- **CDN dependencies in web cockpit.** HTMX and Pico CSS loaded from CDN
  that was unreachable. Replaced with inline CSS + vanilla JS.
- **Expanded `<details>` collapsing on poll.** Agent list innerHTML swap
  destroyed open state every 2s. Fixed by tracking open IDs and restoring.
- **P0/P1 code review fixes.** Send/Stop race, uptime bug, sync.Once→mutex,
  path traversal, decode errors, PID file leak.

### Changed

- **Renamed project from "harness" to "AgentJam".** Module path is now
  `github.com/JamieDF/agentjam`. CLI binary is now `agentjam` (single word).
  Default data directory is now `~/.agentjam/`.

## [0.1.0] - 2026-06-30

### Added

- Initial release: core interfaces, file-backed implementations, CLI, modes.
- `driver.Driver`, `vault.Vault`, `task.Store`, `project.Store`,
  `container.Runtime`, `mode.Loader` interfaces.
- Vault (AES-256-GCM, argon2id, injection templates, audit log).
- Task system (progress logs, acceptance criteria, step tracking).
- Project workspaces (multi-repo YAML).
- Podman container runtime (CLI-based).
- OpenCode driver via Go SDK (written, not live-tested).
- 11 default modes as markdown files.
- Unit tests across all core packages with `-race`.
