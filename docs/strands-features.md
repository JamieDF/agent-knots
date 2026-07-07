# Strands SDK Features — Future Opportunities

Features available in the Strands Agents SDK that agent-jam should utilise.
Checked against installed version (strands-agents 1.45.0).

## ✅ Confirmed for implementation

### 1. Interventions — proper assume/relinquish tool gating

**What:** `Confirm`, `Deny`, `Guide`, `Proceed`, `Transform` actions. Hook into
the agent loop to gate tool execution.

**Plan:** When user assumes control (assistant mode), inject an
`InterventionHandler` that calls `Confirm` before each `BeforeToolCallEvent`.
The cockpit shows the proposed tool call and waits for user approval. On
relinquish, remove the handler. Replaces the current mode-switch-only approach
with actual tool gating.

### 2. Memory — cross-session context for long-running projects

**What:** `MemoryManager` + `MemoryStore`. Agents remember facts, decisions,
user preferences, and project conventions across sessions. Survives restarts
and context compaction.

**Plan:** Configure `MemoryManager` on every agent session. Use the vault as
a persistent backend for memory entries. Agents working on multi-session tasks
can pick up where they left off. The task progress log already does this
structurally — memory adds unstructured contextual memory (user preferences,
coding style, project conventions, decisions made).

### 3. Hooks — observability, cost tracking, progress sync

**What:** 14 hook event types covering every step of the agent loop:
`BeforeToolCallEvent`, `AfterToolCallEvent`, `BeforeModelCallEvent`,
`AfterModelCallEvent`, `MessageAddedEvent`, `AgentInitializedEvent`, etc.

**Plan:**
- **Cost tracking:** `AfterModelCallEvent` provides token counts. Accumulate
  real costs per session instead of current hardcoded estimate.
- **Progress auto-sync:** `AfterToolCallEvent` can auto-log task progress when
  the agent uses file/shell/task tools. No need for the agent to call
  `log_progress` manually — the cockpit does it automatically.
- **Audit logging:** Record every model call and tool invocation for session
  replay and debugging.

### 4. Multi-agent — Graph + Swarm patterns for task decomposition

**What:** `Graph` for deterministic workflows (DAG of agents). `Swarm` for
model-driven handoffs between agents.

**Plan:** Split complex tasks across specialised agents:
- **Planner agent** — reads task, breaks into steps, creates sub-tasks
- **Coder agent** — implements changes, runs tests
- **Reviewer agent** — reviews diffs, checks acceptance criteria
- **Tester agent** — runs test suite, verifies edge cases

The board shows the agent graph. Each sub-agent gets its own session card.
Tasks flow through the graph automatically.

### 6. Checkpoint — session state save/resume

**What:** `strands.experimental.checkpoint`. Save agent state mid-session and
resume later. Survives process restarts.

**Plan:** Enable "pause session, resume tomorrow" workflows. Long-running
tasks can span multiple days. The checkpoint captures the agent's full state
(conversation history, tool context, memory). Restore from checkpoint when
the user returns. Combined with memory (#2) and task progress logs, this
makes agents truly persistent.

### 7. Steering — agent self-correction tied to tasks

**What:** `strands.experimental.steering`. Agents detect and correct their own
mistakes instead of failing silently.

**Plan:** Tie steering handlers to task acceptance criteria. When an agent's
tool output fails a criterion (e.g., "test suite passes"), the steering
handler auto-retries with a different approach. If it fails N times, the task
gets blocked and the user is notified. This makes acceptance criteria
enforceable by the agent itself rather than just documentation.

### 8. Structured output — Pydantic-validated responses

**What:** Agent responses in structured formats (JSON, Pydantic models). Auto
retry on validation errors.

**Plan:** Use structured output for reliable task parsing:
- `create_task` returns a Pydantic `TaskCreateResult` — validated fields
- Progress log entries validated against a `ProgressEntry` schema
- Task status transitions validated (no invalid state changes)
- Acceptance criteria checking produces structured reports

This eliminates the current messy string parsing of tool outputs and ensures
agents produce valid, well-formed task data every time.

---

## Later consideration

### 5. Telemetry — production observability

**What:** Built-in OpenTelemetry integration. Traces every decision in the
agent loop. Export to any OTel-compatible backend.

**When:** After core features stabilise. Useful for debugging agent behavior
in production, but not critical for the local-first use case.

---

## Not applicable (for now)

### Bedrock/cloud deployment
Agent-jam is local-first. Cloud deployment is out of scope.

### Bidirectional voice
Out of scope for a coding agent orchestrator.
