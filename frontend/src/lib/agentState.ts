/** Three-state agent indicator, shared by TaskDetail's watch card and
 * the Board's task card so they always agree on what a given agent state
 * looks like (green/amber/red).
 *
 *   running (turn in flight)     → green, pulsing
 *   errored (last turn threw)    → red, static
 *   idle (between turns, paused, → amber, static
 *         awaiting review, asking)
 *
 * "stopped" is intentionally absent — a stopped session drops out of the
 * live agents list entirely, so neither surface should ever render it.
 */
export type AgentState = 'running' | 'idle' | 'error'

export interface AgentStateToken {
  color: string
  soft: string
  label: string
}

export function computeAgentState(
  hasAgent: boolean,
  running: boolean,
  error: string,
): AgentState | null {
  if (!hasAgent) return null
  return error ? 'error' : running ? 'running' : 'idle'
}

export const AGENT_STATE_TOKENS: Record<AgentState, AgentStateToken> = {
  running: { color: 'var(--ok)', soft: 'var(--ok-soft)', label: 'running' },
  idle: { color: 'var(--warn-ink)', soft: 'var(--warn-soft)', label: 'waiting' },
  // No --err-soft token in the palette, so the error tint is mixed from
  // --err directly (matching how TaskDetail's watch-card border is built).
  error: { color: 'var(--err)', soft: 'color-mix(in srgb, var(--err) 14%, var(--card))', label: 'errored' },
}
