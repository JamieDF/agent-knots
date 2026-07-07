/** SSE client for live agent event streaming. */

export interface SSEEvent {
  html: string
  type: string
  session_id: string
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
