# Strands SDK Features — Future Opportunities

Features available in the Strands Agents SDK that agent-jam could leverage.
Checked against installed version (strands-agents 1.45.0).

## High-value (implement soon)

### Interventions (for proper assume/relinquish)
**Status:** ✅ Available, not wired
**What:** `Confirm`, `Deny`, `Guide`, `Proceed`, `Transform` actions. Hook into
the agent loop to gate tool execution. When user is "driving" (assistant mode),
tools pause and wait for approval. When "watching" (agent mode), tools execute
autonomously.
**How:** Register an `InterventionHandler` on the Agent. On assume, inject a
handler that calls `Confirm` before each `BeforeToolCallEvent`. On relinquish,
remove it. Much cleaner than current mode-switch-only approach.

### Memory (cross-session context)
**Status:** ✅ Available, not wired
**What:** `MemoryManager` + `MemoryStore`. Agents remember facts across sessions.
Store user preferences, project conventions, decisions made. Survives session
restarts and context compaction.
**How:** Configure `MemoryManager` on the Agent. Provides `MemoryAddOptions`,
`MemorySearchOptions`, `MemoryInjectionConfig`. Vault could serve as the
persistent backend for memory entries.

### Hooks (for observability + audit)
**Status:** ✅ Available, not wired
**What:** 14 hook event types: `BeforeToolCallEvent`, `AfterToolCallEvent`,
`BeforeModelCallEvent`, `AfterModelCallEvent`, `MessageAddedEvent`,
`AgentInitializedEvent`, etc. Intercept every step of the agent loop.
**How:** Register hooks via `agent.add_hook()`. Use for:
- Cost tracking (count tokens at each model call)
- Audit logging (record every tool invocation)
- Steering (intercept and redirect tool calls)
- Progress sync (update task progress when tools are called)

## Medium-value (explore next)

### Multi-agent patterns (Graph, Swarm)
**Status:** ✅ Available, not wired
**What:** Built-in orchestration patterns. `Graph` for deterministic workflows
(DAG of agents). `Swarm` for model-driven handoffs between agents.
**How:** Could split complex tasks across specialized agents (planner → coder →
reviewer → tester). Each agent gets a different system prompt and tool set.

### Telemetry (OpenTelemetry)
**Status:** ✅ Available, not wired
**What:** Built-in OpenTelemetry integration. Traces every decision in the agent
loop. Export to any OTel-compatible backend.
**How:** Configure `Telemetry` on session start. Provides visibility into agent
behavior, latency, token usage. Useful for debugging and cost optimization.

### Steering handlers (self-correction)
**Status:** ✅ Available (experimental)
**What:** Agents can detect and correct their own mistakes instead of failing
silently. Part of `strands.experimental.steering`.
**How:** Register steering handlers that validate tool outputs and retry on
failure. Reduces need for user intervention.

## Lower-value (future consideration)

### Checkpoint / Snapshot (session resume)
**Status:** ✅ Available (experimental)
**What:** `strands.experimental.checkpoint`. Save agent state mid-session and
resume later. Survives process restarts.
**How:** Could enable "pause session, resume tomorrow" workflows. Combined with
memory, agents could work on long-running tasks across days.

### Agent Skills (pre-built capabilities)
**Status:** ✅ Available (vended_plugins)
**What:** `strands.vended_plugins.skills`. Pre-built agent skill definitions.
**How:** Give agents domain-specific skills without custom tool development.

### Structured Output
**Status:** ✅ Available (Python + TypeScript)
**What:** Agent responses in structured formats (JSON, Pydantic models). Auto
retry on validation errors.
**How:** Task creation/update could use structured output for reliable parsing.
Progress log entries could be validated against a schema.

## Not applicable (for now)

### Bedrock/cloud deployment
**Status:** Available but not relevant
Agent-jam is local-first. Cloud deployment (AWS Lambda, Fargate, Bedrock
AgentCore) is out of scope for the current vision. May revisit for team/server
deployments later.

### Bidirectional voice
**Status:** Available
Voice interaction is out of scope for a coding agent orchestrator.

---

## Integration Priority

1. **Interventions** — proper assume/relinquish with tool gating
2. **Memory** — cross-session context for long-running projects
3. **Hooks** — observability, cost tracking, progress sync
4. **Multi-agent** — complex task decomposition
5. **Telemetry** — production observability
6. **Checkpoint** — session resume
7. **Steering** — agent self-correction
8. **Structured output** — reliable task parsing
