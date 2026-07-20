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

### 5. Checkpoint — session state save/load
**File:** `src/agent_knots/session/features.py` (`save_checkpoint`, `load_checkpoint`)
**How:** Session state (mode, tokens, task) saved to YAML checkpoint files.
Can be used for pause/resume across restarts.

### 6. Steering — criteria validation via hooks
**File:** `src/agent_knots/session/features.py` (`register_steering_hook`)
**How:** `AfterToolCallEvent` hook checks tool outputs against task acceptance
criteria. Keyword matches auto-mark criteria as met. Registered when a task
is assigned.

### 7. Structured output — task data validation
**File:** `src/agent_knots/session/features.py` (`validate_task_output`)
**How:** Validates task creation/update data against the task model — non-empty
title, valid status and priority enums. Returns structured error reports.

---

## Later consideration

### Telemetry — OpenTelemetry
Not yet integrated. Available in Strands SDK. Low priority for local-first use case.

---

## Not applicable

- Bedrock/cloud deployment
- Bidirectional voice
