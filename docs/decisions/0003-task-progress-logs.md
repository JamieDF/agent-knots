> **Note:** Captured under the prior project name "harness"; see CHANGELOG for the rename.

# ADR 0003: Task state lives in persistent progress logs, not chat

**Status:** Accepted
**Date:** 2026-06-30

## Context

When working on multi-step tasks, AI agents routinely lose progress:

- Context window fills up and gets compacted → task state lost
- Agent crashes or is killed → task state lost
- User switches agents (or models) → new agent doesn't know what's done
- Session ends and resumes later → no record of where we left off

The result: agents re-do work, skip steps, or abandon tasks entirely.

## Options considered

1. **Trust the agent's memory.** Ask the agent to remember where it
   is. Doesn't survive compaction, model swap, or session restart.
2. **Free-form notes in chat.** Agent occasionally writes "TODO: do X
   next." Useful for short tasks, useless for long ones. Notes get
   buried in scrollback.
3. **External structured progress log.** The task object has a
   dedicated progress log field. Every meaningful action appends to it.
   On context compaction, the agentjam summarizes the conversation
   into a progress entry *before* trimming.

## Decision

We chose **option 3**: persistent structured progress logs.

A task looks like:

```yaml
id: T-2026-06-30-001
title: Add dark mode toggle
status: in_progress
acceptance_criteria:
  - "Toggle visible in settings"
  - "Choice persists"
progress:
  - timestamp: 2026-06-30T09:20:14Z
    status: in_progress
    entry: "Created toggle component"
    actions_taken:
      - "write_file: src/components/DarkModeToggle.tsx"
    next_step: "Wire to store"
  - timestamp: 2026-06-30T09:24:33Z
    status: in_progress
    entry: "Wired toggle to store"
    next_step: "Add dark mode CSS variables"
  - timestamp: 2026-06-30T11:05:00Z
    status: blocked
    entry: "Hit contrast issue on navbar"
    blocker:
      description: "Navbar contrast fails WCAG AA"
      options: ["Lighter text", "Stronger background"]
    awaiting: user
```

The agent's tool set includes `task_log_progress` for appending entries.

## Anti-abandonment mechanisms

The progress log enables several anti-abandonment features:

1. **Compaction-safe.** The agentjam pre-summarizes the conversation
   into a progress entry before trimming context. Compaction never
   loses task state.
2. **Handoff-safe.** A new agent (or model) can read the progress log
   to resume exactly where the previous one left off.
3. **Stall detection.** Tasks with no progress entries for N hours
   are flagged as `stalled` in the cockpit.
4. **Acceptance criteria gates.** Tasks can't move to `done` without
   every criterion verified.
5. **Resume protocol.** On session restart, the agent's first action
   is to read the progress log.

## Consequences

Positive:
- Tasks survive context loss.
- Tasks are inspectable (you can read the log without running the
  agent).
- Multi-agent handoff is trivial.
- Acceptance criteria are explicit.

Negative:
- The agent must remember to call `task_log_progress`. (Mitigated
  by making it part of the agent's toolset and persona expectations.)
- The log grows over time. (Mitigated by external storage — YAML
  files on disk.)
- More verbose than free-form notes. (Worth it for the durability.)