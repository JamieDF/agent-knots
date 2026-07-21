# Strands SDK Features — Integration Status

Features available in the Strands Agents SDK (v1.45.0) and their integration
status in agent-knots.

## ✅ Integrated

### 1. Interventions — tool gating for assume/relinquish
**File:** `src/agent_knots/intervention.py`
**How:** `ModeInterventionHandler` gates tool execution based on session mode.
`agent` → Proceed (tools run), `assistant` → Deny (tools blocked).
Wired into every agent session. Verified: assume blocks shell/editor,
relinquish allows them again.

### 2. Memory — cross-session progress injection
**File:** `src/agent_knots/session/features.py` (`inject_memory`)
**How:** When a session starts on a task, recent progress entries from previous
sessions are injected into the system prompt. Agents see what happened before
and continue where others left off. Complements the structured task progress log.

### 3. Hooks — cost tracking + auto progress logging
**File:** `src/agent_knots/hooks.py`
**How:** `AfterModelCallEvent` reads real token counts from model metadata —
replaces the old hardcoded 70-token estimate. `AfterToolCallEvent` auto-logs
`[tool_name]` progress entries on the assigned task — no manual `log_progress`
calls needed. Both registered on every session.

### 4. Multi-agent — delegate_task tool
**File:** `src/agent_knots/session/features.py` (`make_delegate_tool`)
**How:** Agents get a `delegate_task` tool that creates a sub-task and spawns
a new agent session on it. Parent can monitor via `read_task`. Enables
planner→coder→reviewer patterns.

### 5. Steering — advisory criteria nudges via hooks
**File:** `src/agent_knots/session/features.py` (`register_steering_hook`)
**How:** `AfterToolCallEvent` hook checks tool outputs against unmet task
acceptance criteria via keyword match. On a match it logs a suggestion to
verify and call `mark_criterion_met` — it does **not** mark the criterion
met itself. The actual `done`-transition gate
(`TaskStore._validate_transition`) only respects explicit
`mark_criterion_met` calls, so a fuzzy keyword match can't quietly
satisfy real enforcement.

### 6. Structured output — task data validation
**File:** `src/agent_knots/task/tools.py` (`validate_task_output`)
**How:** Validates task creation/update data before it hits the store —
non-empty title, valid status and priority enums. Wired into `create_task`
and `update_task`, turning what used to be an uncaught `ValueError` from
an invalid priority/status into a structured tool error.

---

## Later consideration

### Telemetry — OpenTelemetry
Not yet integrated. Available in Strands SDK. Low priority for local-first use case.

---

## Not applicable

- Bedrock/cloud deployment
- Bidirectional voice

## Removed

### Checkpoint — session state save/load
`save_checkpoint`/`load_checkpoint` were implemented (arbitrary session
dict → YAML file) but never called from anywhere — no CLI command, no API
endpoint, nothing resumed from a checkpoint. Removed rather than wired up:
cross-session continuity is already covered by `inject_memory` (recent
progress-log entries injected into a new session's system prompt), and a
real pause/resume feature would need to serialize actual conversation
state, not just a loosely-typed metadata dict — that's a real design
decision to make later, not something worth reviving as-is. See
[roadmap.md](../roadmap.md) if this comes back as a scoped feature.
