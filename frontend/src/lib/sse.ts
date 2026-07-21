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
  onClose?: () => void,
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

  es.addEventListener('close', () => {
    onClose?.()
    es.close()
  })

  es.onerror = () => {
    // EventSource auto-reconnects. If it can't, we'll get repeated errors.
    // The parent component should handle cleanup via the returned EventSource.
  }

  return es
}
