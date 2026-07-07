import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ChatInput from '../components/ChatInput'
import { assumeAgent, relinquishAgent, sendMessage, type AgentInfo, fetchAgents } from '../lib/api'
import { subscribeToAgent, type SSEEvent } from '../lib/sse'

interface EventItem {
  id: number
  html: string
}

function AgentFocus() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const eventsEndRef = useRef<HTMLDivElement>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [mode, setMode] = useState<string>('agent')
  const counterRef = useRef(0)

  // Fetch agent info.
  useEffect(() => {
    if (!id) return
    let mounted = true
    const poll = async () => {
      try {
        const data = await fetchAgents()
        if (!mounted) return
        const found = data.agents.find(a => a.id === id)
        if (found) {
          setAgent(found)
          setMode(found.mode)
        }
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => { mounted = false; clearInterval(interval) }
  }, [id])

  // Subscribe to SSE.
  useEffect(() => {
    if (!id) return
    const es = subscribeToAgent(
      id,
      (evt: SSEEvent) => {
        counterRef.current += 1
        setEvents(prev => [...prev.slice(-200), { id: counterRef.current, html: evt.html }])
      },
      () => {
        setEvents(prev => [...prev, { id: counterRef.current + 1, html: '<p style="font-size:12px;color:var(--muted);padding:10px">Session ended.</p>' }])
      },
    )
    return () => es.close()
  }, [id])

  // Auto-scroll.
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  const handleAssume = useCallback(async () => {
    if (!id) return
    await assumeAgent(id)
    setMode('assistant')
  }, [id])

  const handleRelinquish = useCallback(async () => {
    if (!id) return
    await relinquishAgent(id)
    setMode('agent')
  }, [id])

  const handleSend = useCallback(async (message: string) => {
    if (!id) return
    // Echo user message immediately.
    counterRef.current += 1
    const now = new Date()
    const ts = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
    const escapedMsg = message.replace(/</g, '&lt;')
    const userHtml = `<div class="prose-row prose-user"><div class="prose-avatar user">Y</div><div class="prose-content"><div class="prose-text">${escapedMsg}</div></div><div class="prose-ts">${ts}</div></div>`
    setEvents(prev => [...prev, { id: counterRef.current, html: userHtml }])

    await sendMessage(id, message)
  }, [id])

  if (!id) return null

  const isDriving = mode === 'assistant'

  return (
    <div className="focus-view">
      {/* Left sidebar — agent context */}
      <div className="focus-left">
        <button className="btn btn-ghost" onClick={() => navigate('/')} style={{ alignSelf: 'flex-start', marginBottom: 8 }}>
          ← Back
        </button>
        <div>
          <div className="stat-label">Status</div>
          <div className="stat-value">
            <span style={{ color: agent?.running ? 'var(--running)' : 'var(--muted)' }}>
              {agent?.running ? '● running' : '○ idle'}
            </span>
          </div>
        </div>
        <div>
          <div className="stat-label">Mode</div>
          <div className="stat-value">{mode}</div>
        </div>
        <div>
          <div className="stat-label">Agent ID</div>
          <div className="stat-value" style={{ fontSize: 11 }}>{id}</div>
        </div>
        {agent?.task_id && (
          <div>
            <div className="stat-label">Task</div>
            <div className="stat-value" style={{ fontSize: 12 }}>{agent.task_id}</div>
          </div>
        )}
      </div>

      {/* Center — event stream */}
      <div className="focus-center">
        <div className="agent-header">
          <button className="back-btn" onClick={() => navigate('/')} title="Back to overview">←</button>
          <div className="agent-id">
            <strong>{id}</strong>
          </div>
          <span className={`mode-pill ${isDriving ? 'assumed' : ''}`} id="mode-pill">
            <span className="pill-dot" />
            {isDriving ? 'driving' : 'watching'}
          </span>
          <div className="spacer" />
          {isDriving ? (
            <button className="btn btn-relinquish" onClick={handleRelinquish}>
              Relinquish
            </button>
          ) : (
            <button className="btn btn-assume" onClick={handleAssume}>
              Assume
            </button>
          )}
        </div>
        <div className="focus-events" id="focus-events">
          {events.length === 0 && agent?.running && (
            <p style={{ color: 'var(--muted)', fontSize: 12, padding: 10 }}>Waiting for events...</p>
          )}
          {events.map(evt => (
            <div key={evt.id} dangerouslySetInnerHTML={{ __html: evt.html }} />
          ))}
          <div ref={eventsEndRef} />
        </div>
        <ChatInput onSend={handleSend} disabled={!agent?.running} />
      </div>

      {/* Right sidebar — stats */}
      <div className="focus-right">
        <div style={{ marginBottom: 16 }}>
          <div className="stat-label">Tokens</div>
          <div className="stat-value">{agent?.tokens_used.toLocaleString() ?? 0}</div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <div className="stat-label">Cost</div>
          <div className="stat-value">${agent?.cost_usd.toFixed(3) ?? '0.00'}</div>
        </div>
        <div>
          <div className="stat-label">Project</div>
          <div className="stat-value" style={{ fontSize: 12, color: 'var(--muted)' }}>
            {agent?.project_id || '—'}
          </div>
        </div>
      </div>
    </div>
  )
}

export default AgentFocus
