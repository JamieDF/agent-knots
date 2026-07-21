# Work Plan: Atelier Cockpit Build-Out

Phased plan for implementing the redesign in `frontend/` (React + TS + Vite) with FastAPI backend extensions. Phases are ordered by dependency and value; each ends in a shippable state. Est. sizes: S < 1 day, M 1–3 days, L 3–5 days.

## Phase 0 — Foundations (M) — ✅ done 2026-07-21
- [x] Theme system: CSS custom properties on `body[data-theme]`, light/dark token sets from README, toggle in top bar, persist in localStorage.
- [x] Fonts: DM Sans + DM Mono (Google Fonts, unchanged from before).
- [x] Desk shell: dotted-grid background (`DeskLayout.tsx`), floating top bar (nav pill, workspace switcher, stats pill, bell, theme — **+ New session renders disabled**, wiring lands Phase 2/3), centered-column page scaffold.
- [x] Workspace scope context: reactive `useWorkspaceScope()`, `?ws=` URL param so it survives reload (`lib/workspaceContext.tsx`).
- [x] Shared primitives: Card, Chip, Toggle, StatusDot, PriorityLabel, SectionLabel, Dialog, Mono (`components/primitives/`). Status/priority color maps (`lib/statusColors.ts`, `lib/priorityColors.ts`).
- [x] Router: HashRouter → BrowserRouter, with a FastAPI catch-all SPA-fallback route for deep links (`server.py`).
- [x] **Backend — pulled forward from later phases, not "none" as originally scoped**: full SSE rewrite from server-rendered HTML fragments to structured JSON events (`events.py::serialize_event()`), plus a fan-out fix (`Session.subscribe()`/`_broadcast()`) so multiple simultaneous viewers of one agent no longer race for events on a single queue. New `EventType` members: `AUTO_LOG`, `STEER`, `DELEGATE`, `CHECKPOINT`, `USER`, `ENDED`. Justification: this was backend-only churn, safe to land before any Atelier-styled consumer existed, and the fan-out fix is also a prerequisite for Phase 2's multi-viewer Dashboard cards.
- Note: `Overview.tsx`→`Dashboard.tsx` and `AgentFocus.tsx`→`AgentThread.tsx` renamed; Agent Thread got an interim structured-event renderer (same look, real fields instead of HTML/regex scraping) so it isn't dead between now and its full Phase 3 rebuild. `NewSessionDialog.tsx` (confirmed dead code) deleted.

## Phase 1 — Ticket core: Tasks screen + Task Detail (L) — ✅ done 2026-07-21
The product spine. Includes the current app's biggest known gaps.
- [x] Combined Tasks screen: Board/List tabs, shared header (+ New task, ⚙ Stages) — `views/Tasks.tsx` shell + `views/tasks/{Board,List}.tsx`.
- [x] Board: stage-driven columns (5 enabled by default, Abandoned off — `lib/stages.ts`), blocked/planned badges, expand-in-place cards (stage chips, Details, Start session), column + quick-create.
- [x] List: stage filter chips, task rows.
- [x] Task Detail: lifecycle strip, header actions, steps (+sub_steps), **clickable acceptance criteria** (fixes read-only criteria — `POST /api/tasks/{id}/criteria/toggle`), progress log, side blocks (session info, tools used, related tasks, vault creds), tick-free simplified metadata block, delete.
- [x] Task create/edit dialog (`components/TaskDialog.tsx`): chip tags, row-list criteria/steps editors, review-gate select, "✨ Draft with agent". **Fixes the known edit no-ops (description/criteria/tags).**
- [x] Backend: `PATCH /api/tasks/{id}` now accepts description/tags/acceptance_criteria/steps (was silently dropping them — real bug, now fixed, with criteria_met/step-status preserved across edits by matching on text); `POST /api/tasks/{id}/criteria/toggle`; `Task.review_gate` field (`auto`/`manual`/`none`, persisted, enforcement deferred to Phase 4); `GET /api/agent/{id}`; `POST /api/tasks/draft`; `_task_to_response()` now includes `criteria_met` (was omitted entirely — the frontend had no way to know which criteria were already met on load).
- Scope trims from the source README dialog spec: no workspace/project reassignment in the dialog (out of scope for Phase 1), sub-step editing is display-only (matches the dialog spec, which also doesn't cover it), progress-log blocker suggested-answer buttons deferred to Phase 3 (needs live SSE blocker delivery, not just the stored log entry).
- Playwright: `#/board`→`/tasks?view=board` etc. across the suite; rewrote the now-obsolete "Tasks ▾ dropdown" test as a Board/List tab-pill test; fixed status-change tests to go through the Edit dialog (no more inline status `<select>` on Task Detail); added `aria-label`s to TaskDialog's Priority/Status/Review-gate selects for robust targeting. 36/37 non-LLM-dependent tests verified passing against a live server in an isolated temp home.

## Phase 2 — Dashboard (M)
- [ ] Workspace clusters with dashed borders + header pills.
- [ ] Blocker hero with inline answers (wire to session reply endpoint).
- [ ] Running agent 2-up cards (live via SSE), delete session.
- [ ] Up-next queue + Start (session created with task memory), auto-assign toggle (config only in v1), pipeline + review chips.
- Backend: none beyond existing sessions/tasks/SSE; auto-assign flag on workspace config.

## Phase 3 — Agent Thread (L)
- [ ] Three-zone layout, collapsible goal rail (⌘B).
- [ ] Event renderers: message, thinking (collapsible), tool card, auto-log, steer, delegation (expandable nested thread), checkpoint (+revert), ask, user, ended.
- [ ] Composer states: driving / watching-locked / ended; Assume/Relinquish; Stop; delete.
- [ ] Right rail tabs: Terminal, Files, Preview (placeholder ok in v1).
- [ ] Replay scrubber on ended sessions (client-side over event history).
- Backend: checkpoint/revert endpoints (worktree snapshot) — can stub with git stash/tag initially; delegation events already exist via delegate_task.

## Phase 4 — Workflows + Review (L)
- [ ] Workflows screen: Board stages config (toggle, add; persist), Default agents (Planner/Builder/Reviewer) with config dialog (model/trigger/prompt), generated Current-workflow diagram reacting to config, pipeline templates.
- [ ] Review queue: pending diffs, approve/reject/approve-all, policy flags.
- [ ] Auto-review banner + Run review now on Task Detail.
- Backend (largest new surface): stages config store; role-agent config + trigger hooks in the session lifecycle; diff-capture layer (agent edits land as pending diffs before worktree commit) + approve/reject; reviewer-agent run.
- Note: diff capture can ship after the UI using a "post-hoc review" mode (diffs shown from git, approve = no-op commit) if needed to decouple.

## Phase 5 — Vault + Settings (M)
- [ ] Vault: lock/unlock, credentials list + add, injection template chips, audit log. (Backend vault + audit exist in CLI; add web endpoints. Never send secret values to the client.)
- [ ] Settings: Usage card (token metering exists; per-provider estimate calc), multi-provider config + default, consolidated Tools (+ custom tool dialog, delete), Policies, MCP servers, Integrations, Workspaces CRUD.
- Backend: multi-provider settings schema (currently single provider), policy store + enforcement hooks, MCP server registry, workspace CRUD (exists).

## Phase 6 — Entry flows + notifications (S/M)
- [ ] Setup wizard (auto-route when unconfigured), token login page.
- [ ] Notification bell: derive from SSE (blocker, task done, tests); dropdown deep-links; phone-push toggle (config only unless push infra exists).

## Suggested sequencing / parallelism
Phase 0 → 1 → 2 → 3 sequential (each builds on the last). Phase 5 can run parallel to 3–4 (different backend surface). Phase 4 last of the big ones — it has the most new backend. Total rough estimate: 4–6 engineer-weeks.

## Definition of done (per screen)
- Matches prototype pixel-values in both themes.
- All interactions in the prototype work against real data.
- Empty states handled (no workspaces, no tasks, no pending reviews, locked vault).
- Keyboard: Enter sends, Esc closes dialogs, ⌘B rail toggle.
- No regressions to the SSE live-update behavior of the current app.
