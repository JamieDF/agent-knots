/** SSE client for live agent event streaming.
 *
 * Wire format matches the backend's Event dataclass (agent_knots.events,
 * serialized via serialize_event()) — structured JSON, not pre-rendered
 * HTML. The frontend owns all rendering now.
 */

export interface ToolCallData {
  id: string
  name: string
  args: Record<string, unknown>
}

export interface ToolResultData {
  tool_call_id: string
  stdout: string
  stderr: string
  exit_code: number
  error: string
}

export interface SSEEvent {
  type: string
  session_id: string
  timestamp: number
  message: string
  tool_call: ToolCallData | null
  tool_result: ToolResultData | null
  error: string
  data: Record<string, unknown> | null
}

export function subscribeToAgent(
  agentId: string,
  onEvent: (event: SSEEvent) => void,
): EventSource {
  const es = new EventSource(`/api/agent/${agentId}/events`)

  es.onmessage = (e) => {
    try {
      const data: SSEEvent = JSON.parse(e.data)
      onEvent(data)
    } catch {
      // ignore malformed events
    }
  }

  // The backend never emits a named "close" SSE event (only plain data:
  // messages plus a "connected" event on open) — a real end-of-session
  // signal is a normal event with type "ended", already handled via
  // onEvent like any other event. A previous version of this listened
  // for 'close' anyway and fabricated a second, synthetic "ended" event
  // when it (never) fired — dead code, removed rather than kept as a
  // trap for the next person who assumes it does something.

  es.onerror = () => {
    // EventSource auto-reconnects. If it can't, we'll get repeated errors.
    // The parent component should handle cleanup via the returned EventSource.
  }

  return es
}
