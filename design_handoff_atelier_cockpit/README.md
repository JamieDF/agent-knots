# Handoff: agent-knots Cockpit Frontend Redesign ("Atelier")

## Overview

Complete redesign of the agent-knots web cockpit (the React SPA in `frontend/`). agent-knots is a local-first multi-agent coding assistant: agents work coding tasks in isolated workspaces, log progress against tickets, and stop to ask the human when blocked. The redesign — internally "Atelier" (spatial desk) — reorganizes the whole UI around the **ticket lifecycle** (draft → open → in progress → review → done) and adds surfaces the current app lacks: Vault, Review queue, Workflows, notifications, and workspace scoping.

The full clickable prototype is `Atelier Prototype.dc.html` in this bundle. It is the single source of truth for look, layout, and interaction.

## About the Design Files

The files in this bundle are **design references created in HTML** — prototypes showing intended look and behavior, NOT production code to copy. The task is to **recreate these designs in the existing `frontend/` React + TypeScript codebase** (Vite SPA, react-router, the existing `api.ts` client and SSE event stream), using its established patterns. Extend the FastAPI backend where the design assumes endpoints that don't exist yet (flagged per-screen below and in WORKPLAN.md).

The prototype is a self-contained interactive HTML document with its own tiny runtime. Open it in a browser and click through every surface before starting. Ignore its internal templating mechanics (`sc-if`, `sc-for`, `{{ }}`) — read it for markup structure, inline styles (all values are literal), and the state logic in its `<script>` class at the bottom of the file.

## Fidelity

**High-fidelity.** Colors, typography, spacing, radii, and shadows are final and should be recreated exactly (all values are inline in the prototype and listed under Design Tokens). Interactions shown in the prototype (mode lockout, criteria toggling, review approval, stage config, etc.) are the intended behavior. Mock DATA in the prototype (task names, sessions, token counts) is placeholder — wire to real API data.

## Information Architecture

Top-level nav (floating pill, top bar): **Dashboard · Tasks · Review · Workflows · Vault · Settings**

Also in the top bar, left → right:
- Workspace scope switcher pill: `All | <workspace…>` — filters Dashboard, Tasks, and stats globally
- Stats pill: `N agents · NK tok` (no cost here — cost lives in Settings → Usage)
- Notification bell (◷) with amber badge count + dropdown
- Theme toggle (☾/☀)
- `+ New session` (accent button)

Secondary screens: Agent Thread (from Dashboard/task), Task Detail (from Tasks), Setup Wizard, Login. Dialogs: task create/edit, new session, custom tool, workspace, role config.

## Visual Language ("Atelier")

- Desk metaphor: a dotted-grid background (`radial-gradient(var(--dot) 1px, transparent 1px)`, 22px grid) with floating white cards (soft, layered shadows) sitting on it. Screens are **centered columns** (Dashboard 850px, Tasks list 1000px, board 1240px, Thread 1280px), never edge-to-edge panels.
- Light + dark themes via CSS custom properties on `body[data-theme]` (full token table below). Theme toggle in the top bar; persist choice.
- Fonts: **DM Sans** (UI) + **DM Mono** (ids, paths, tokens, timestamps, anything machine-y). Google Fonts.
- Accent: violet `#6c5ce7` (dark mode `#8f7ff2`). Amber = "needs human". Green = running/ok. Purple `#a06be0` = review.

## Screens

### 1. Dashboard (`/`)
Centered 850px column. One **workspace cluster** per workspace (scope switcher can narrow to one). Each cluster is wrapped in a `2px dashed var(--line2)` rounded-20px border with 20px padding — a "desk zone".

Cluster contents, top to bottom:
1. **Header row**: white pill (workspace name bold 13.5px, repo in 11px mono muted, runtime chip 9.5px mono) + summary text ("3 agents · 8 open tasks", 12px muted, nowrap).
2. **Blocker hero** (if any agent is blocked): full-width card, `2px solid var(--warn)` border, shadow-lg. Header: amber dot, task title, NEEDS YOU chip (9.5px, amber soft bg), task id (clickable → Task Detail), right-aligned mono meta (`sess-id · 4/7 steps · 92.1K tok`). Body: the agent's question in italic 12.5px, then an answer row: suggested-answer buttons (accent + outline) and a flex-1 "Reply…" ghost input that opens the Agent Thread. Answering resumes the agent (task → in_progress, blocker cleared, reply appended to thread).
3. **Running agents, 2-up grid** (16px gap): compact cards — header (green dot, title 12.5px bold, steps `2/3` mono right), body strip (`var(--card2)` bg: current action 11px mono + last tool 10px mono muted), footer (mode word colored, tokens, uptime, ✕ delete, "Open →" accent link).
4. **Footer row**: "Up next" dashed-border card (flex-1) — queued open/planned tasks with priority dot, title, meta, and `▶ Start` (green soft chip); header has "auto-assign · max 2" + toggle. Beside it a 250px column of two chips: pipeline counts (`draft · building · review · done` mono) and "N diffs waiting → Review".

**Start** creates a session on that task (memory = prior progress entries), flips the task to in_progress, and adds the agent card live.

### 2. Agent Thread (from any agent "Open →")
1280px centered card, full height, three zones:

- **Header**: ← back, status dot, title, sess-id, mode chip (DRIVING amber / WATCHING gray), model chip, ⌘B rail toggle, right: `tokens · cost · up time` mono, **Assume/Relinquish** button (amber soft), **■ Stop**, **✕ delete**.
- **Left goal rail** (260px, `var(--card2)`, collapsible via ⌘B): Goal (task title → Task Detail, description), Steps with progress bar and ✓/○ list, Criteria with ✓/○ list.
- **Center thread**: event stream. Event renderings:
  - agent message: 26px round avatar "A" (accent soft) + 13px text
  - thinking: "…" avatar, italic muted; **click collapses/expands** to "thinking — click to expand"
  - tool call: "$" avatar + mono block in bordered `var(--card2)` card (pre-wrap)
  - auto-log line: `↳ [shell] auto-logged to task-XXXX progress` 10.5px mono, indented
  - steering nudge: `⌁ …` italic accent text in accent-soft rounded box, indented
  - **delegation card**: bordered, caret ▸/▾ header (SUB-AGENT label, sess/task id, title, status chip) — expands to nested sub-agent mini-thread
  - checkpoint: horizontal rule with `⚑ checkpoint · name` + accent "revert to here" (appends a revert log line)
  - blocker ask: "A" amber avatar, question in amber-soft bubble
  - user reply: "Y" accent avatar, accent-soft bubble
  - session end: hairline rule "session ended"
- **Composer** (bottom), three states: **driving** → input + Send (Enter sends); **watching** → locked bar "👁 Watching — the agent is driving. Assume control to send messages." + Assume button; **ended** → replay scrubber (range input over event count, scrubbing truncates the visible thread) + "session ended" note.
- **Right rail** (290px, tabs): **Terminal** (mono log), **Files** (M/A/R colored ops + paths), **Preview** (proxied dev-server placeholder with URL bar).

### 3. Tasks (`/tasks`) — Board + List, one screen, tab switch
Shared header row (centered, 1240px board / 1000px list): `Board | List` tab pill, right-aligned `+ New task` (accent) and `⚙ Stages` (→ Workflows). Buttons `white-space:nowrap; flex-shrink:0`.

**Board tab**: columns = **enabled stages from Workflows config** (default Draft / Open / In progress / Review / Done; Abandoned exists but is off by default). Columns flex evenly, max 250px, centered. Column header pill: status dot, label, count, `+` (opens create dialog pre-set to that stage's first status). Cards: 3px left border in priority color, title, badge row (**wraps**): id mono, AGENT chip (green) when a session is on it, ⚠ BLOCKED (amber) / PLANNED (accent) sub-status badges, priority label right. **Click expands the card in place**: stage chips to move it, "Details →", "▶ Start session" (when no agent).

Status→stage mapping: `open+planned → Open`, `in_progress+blocked → In progress`; blocked/planned surface as badges, not columns.

**List tab**: single card. Filter chips reflect the same enabled stages (All + one per stage; a stage chip filters to all its statuses). Rows: 5-col grid (title+id / workspace / status icon+label colored / priority / steps meta), click → Task Detail.

### 4. Task Detail
880px centered card.

- **Header row**: ←, id mono, status chip, priority, workspace, PR chip (`PR #142 · open`, only status=review), then: **"● Agent active — open"** (green) or **"▶ Start agent on this task"** (accent), **Edit**, **✕ delete**.
- **Lifecycle strip** (`var(--card2)` bar): draft → open → in progress → review → done dots+labels; past = green, current = accent (amber if blocked), future = muted; note for blocked/planned/abandoned. Right: review-gate label (`🛡 auto-review on completion` / `review: ask me` / `no review gate`).
- **Auto-review banner** (accent-soft, only status=review + gate=auto): "🛡 Auto-review queued…" + **Run review now** → appends reviewer progress entry; promotes to done iff all criteria met.
- **Body**: title + tag chips; description card; **Steps** (✓ done rows struck-through, active highlighted, notes, nested sub_steps as bullet list); **Acceptance criteria** — clickable checkbox rows (toggle met; met = accent box + accent-soft row) with the hint "Done is gated on all criteria being marked met"; **Progress log** — newest first, cards (blocked entries amber-bordered; blocker entries include the question + suggested-answer buttons + Open thread / Skip step / Reassign).
- **Side blocks** (right column, 190px min): session info (id, mode, model, tokens), Tools used (name ×count), Related tasks (linked, status-colored), vault creds used (⚿).
- **Footer tick timeline**: `started ————•——•—•———— now`, dots colored by entry type (amber blocked, accent milestone).

### 5. Review (`/review`)
860px column. Header card: title, "N pending" amber chip, explainer, **Approve all**. One card per pending diff: header (file mono, `+adds`/`−dels` colored, session · task, optional `⚑ policy` amber chip, **✓ Approve** / **✕ Reject**), body = mini diff (mono 11.5px, +green/−red lines). Approved → "Approved — committed" chip; rejected → "Rejected — agent notified".

### 6. Workflows (`/workflows`)
860px column, four cards:

1. **Current workflow** — generated diagram of live config: enabled stages as nodes (dot + label + note: "you or ✨ agent drafts" / "blocked waits here" / "criteria gated") joined by →; under a stage, a dashed accent chip for each enabled default agent that fires there (◆ Planner → leaves draft, ⚒ Builder → started, 🛡 Reviewer → enters review). Chip click opens that agent's config. Footer: "⚠ blocked shows inside In progress · done gate: review config on each ticket · all criteria met". **Must re-render when stages/roles change.**
2. **Board stages** — row per stage: ⠿ drag handle, label, status mapping mono, "required" (draft/done), on/off toggle. + Add stage.
3. **Default agents** — Planner / Builder / Reviewer rows: icon tile, name, model chip, description, "fires <trigger>" accent line, **Configure** (dialog: model select, trigger select [leaves draft / is started / enters review / manual], system prompt textarea, read-only allowed-tools list), on/off toggle.
4. **Start a pipeline** — templates (Plan → Code → Review; Code → Review; Security sweep) with "Use on a task…".

### 7. Vault (`/vault`)
Locked: 420px centered card — 🔒 tile, "Vault is locked", "AES-256-GCM encrypted credential store", passphrase input, **Unlock vault**. Unlocked: 900px column — **Credentials** card (UNLOCKED green chip, Lock link, + Add credential; rows: id mono / description / injection template chips (`env:GH_TOKEN`, `file:~/.aws/creds`, `wrapper`) / last-used) and **Audit log** card (mono rows: ts / action colored [INJECT accent, READ amber, UNLOCK green] / cred / actor).

### 8. Settings (`/settings`)
800px column, cards in order:
1. **Usage** — "Token counts are exact; cost is an estimate from each provider's pricing." Stat row (tokens today, month, ~$ today, ~$ month), By provider bars (mono name, bar, `tok · ~$`), Top tasks by tokens bars.
2. **Model providers** — rows: name / model mono / base URL mono / key status dot ("key set" green, "no key" gray) / DEFAULT chip or "Set default". + Add provider.
3. **Tools** — built-in + custom in one list: name mono, description, BUILT-IN/CUSTOM chip, toggle, ✕ (custom only). **+ Custom tool** dialog: name, description, shell command with `{param}` braces, params (`name:type, …`).
4. **Policies** — toggle rows (migrations/ guard, pause after 2 test failures, spend cap, no sudo) + "+ Add rule".
5. **MCP servers** — name, "N tools exposed", toggle, + Add MCP server.
6. **Integrations** — GitHub (connected status, PR-on-review behavior), Phone push toggle.
7. **Workspaces** — id mono / repo / runtime / counts / Edit / ✕. Dialog: id, repo, runtime select (subprocess/in-process).
8. **First-run flows** — buttons to preview Setup wizard & Login.

### 9. Setup Wizard & Login
Wizard (520px card): logo tile, welcome copy, provider preset chips (MiniMax active / OpenAI / Anthropic / Ollama / Custom), model id, API key + plain-YAML warning, Skip / **Finish setup →**. Login (420px): logo, "paste the access token printed by `agent-knots cockpit launch --web`", token input, Continue, "local-only · token stored as a cookie" note.

### 10. Notifications (top bar)
Bell + amber count badge (pending blockers). Dropdown 340px: rows (icon colored / title / `source · time` mono) → deep-link (blocker → thread, done → task detail); footer "Push blockers to phone" toggle.

### 11. Dialogs
- **Task create/edit**: title; **✨ Draft with agent** (enabled once title present; fills description, criteria, steps, tags — user edits before save); description; workspace/priority/status selects; **tags as chip input** (Enter/comma adds, ×/backspace removes); **criteria as row list** (○ prefix, inline input, ×, + Add criterion, "gates done" hint); **steps as numbered row list** (①②③, same pattern); **review gate select** (auto / ask me / none — copy in prototype); esc-to-cancel note, Cancel / Create-or-Save. Editing preserves met/done state of unchanged items.
- **New session**: attach-to-task select ("prior progress is injected as memory"), prompt, mode / workspace / model selects.

## State & Data

Core entities (see prototype state for exact shapes): Workspace {id, repo, runtime}; Task {id, ws, title, desc, status(8: draft open planned in_progress blocked review done abandoned), prio(URGENT HIGH MED LOW), tags[], reviewCfg(auto|manual|none), criteria[{t,met}], steps[{t,done,notes?,sub_steps?}], progress[{status,entry,when,blocked,question?,options?}]}; Agent/Session {id, ws, taskId, title, mode(driving|watching), blocked, stopped, action, lastTool, tokens, cost, uptime, question?}; per-session event stream (kinds: agent, think, tool, log, steer, delegate(+subEvents), checkpoint, ask, user, ended); Stage {key,label,statuses[],on}; Role {key,name,icon,desc,model,trigger,prompt,tools[],on}; ReviewItem {session,task,file,adds,dels,status,policy?,diff[]}; Provider; Tool; Policy; McpServer; Credential; AuditRow.

Status colors: draft `var(--mut2)` ○ · open `var(--ink2)` ◌ · planned `var(--acc)` ◔ · in_progress `var(--ok)` ● · blocked `var(--warn-ink)` ⚠ · review `#a06be0` ◉ · done `var(--ok)` ✓ · abandoned `var(--mut2)` ✕. Priority: URGENT `var(--err)`, HIGH `var(--warn-ink)`, MED `var(--acc)`, LOW `var(--mut)`.

Key behaviors to preserve: workspace scope filters everything; answering a blocker resumes the agent everywhere it appears; assume/relinquish gates the composer; criteria checkboxes gate done; auto-review promotes only when all criteria met; stage config drives board columns, list chips, and the workflow diagram; starting an agent injects task progress as memory.

## Design Tokens

Light: `--bg #eceef2 · --dot #cdd2db · --card #fff · --card2 #fafbfc · --line #eef0f3 · --line2 #dcdfe5 · --ink #23262b · --ink2 #5a6069 · --mut #8a8f99 · --mut2 #a3a8b2 · --acc #6c5ce7 · --acc-soft #f7f5ff · --acc-ink #fff · --ok #22c07a · --ok-soft #e3f6ec · --warn #f0a72e · --warn-ink #b07a10 · --warn-soft #fdf1dc · --err #e05252 · --mono-bg #f2f3f6 · --shadow 0 6px 20px rgba(30,35,50,.12) · --shadow-lg 0 16px 44px rgba(30,35,50,.22)`

Dark (`body[data-theme=dark]`): `--bg #191b20 · --dot #2c3038 · --card #23262d · --card2 #1e2126 · --line #2e323a · --line2 #3a3f48 · --ink #dfe2e8 · --ink2 #aab0ba · --mut #767c87 · --mut2 #5c6270 · --acc #8f7ff2 · --acc-soft #2a2740 · --acc-ink #191b20 · --ok #3fd08e · --ok-soft #173226 · --warn #e8b04a · --warn-ink #e8b04a · --warn-soft #332a17 · --err #e06a6a · --mono-bg #1a1c22 · shadows: rgba(0,0,0,.35)/.5`

Radii: cards 14–16px, buttons/inputs 8–10px, chips 6–10px, pills 12px, workspace border 20px. Type scale: 21px page titles, 13–14px headings, 12–13px body, 10–11.5px meta/mono, 9.5–10px chips; section labels 10.5–11px 700 uppercase +.06em tracking. Spacing: 22px grid; card padding 14–18px h / 10–14px v; column gaps 14–18px; cluster gap 34px. Toggles: 36×20 (32×18 small), knob 16px, accent when on.

## Assets

None — no images or icon fonts. All "icons" are unicode glyphs (◆ ⚒ 🛡 ⚑ ⌁ ↳ ⚿ ◷ ☾ ☀ ⠿ ✨ ▶ ■ ✕ ✓ ⚠). Keep or swap for the codebase's icon set (lucide-react is fine) at equal sizes.

## Files

- `Atelier Prototype.dc.html` — the full interactive prototype (all screens, dialogs, both themes). **Primary reference.**
- `Dashboard Options.dc.html` — dashboard exploration history (turn 4 = chosen direction). Context only.
- `Redesign Directions.dc.html`, `Redesign Directions v2.dc.html`, `Atelier Prototype v2.dc.html` — earlier explorations. Context only; the main prototype supersedes them.
- `WORKPLAN.md` — phased implementation plan with backend dependencies.
