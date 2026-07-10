import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ChatInput from '../components/ChatInput'
import { assumeAgent, relinquishAgent, sendMessage, fetchTask, type AgentInfo, fetchAgents, type TaskDetail } from '../lib/api'
import { subscribeToAgent, type SSEEvent } from '../lib/sse'

interface EventItem { id: number; html: string; type: string; text: string }
type Tab = 'review' | 'terminal' | 'browser'

function AgentFocus() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const eventsEndRef = useRef<HTMLDivElement>(null)
  const termEndRef = useRef<HTMLDivElement>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [mode, setMode] = useState<string>('agent')
  const [tab, setTab] = useState<Tab>('terminal')
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [termLines, setTermLines] = useState<string[]>([])
  const counterRef = useRef(0)

  // Fetch agent + task info.
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
          if (found.task_id) {
            fetchTask(found.task_id).then(t => setTask(t)).catch(() => {})
          }
        }
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 3000)
    return () => { mounted = false; clearInterval(interval) }
  }, [id])

  // Subscribe to SSE — also extract terminal output.
  useEffect(() => {
    if (!id) return
    const es = subscribeToAgent(
      id,
      (evt: SSEEvent) => {
        counterRef.current += 1
        setEvents(prev => [...prev.slice(-200), { id: counterRef.current, html: evt.html, type: evt.type, text: stripHtml(evt.html) }])
        // Capture tool results for terminal.
        if (evt.type === 'tool_result' && evt.html) {
          const text = stripHtml(evt.html)
          setTermLines(prev => [...prev.slice(-500), text])
        }
      },
      () => {
        setEvents(prev => [...prev, { id: counterRef.current + 1, html: '<p style="font-size:12px;color:var(--muted);padding:10px">Session ended.</p>', type: 'state_change', text: 'Session ended.' }])
      },
    )
    return () => es.close()
  }, [id])

  useEffect(() => { eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [events])
  useEffect(() => { termEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [termLines])

  const handleAssume = useCallback(async () => { if (!id) return; await assumeAgent(id); setMode('assistant') }, [id])
  const handleRelinquish = useCallback(async () => { if (!id) return; await relinquishAgent(id); setMode('agent') }, [id])
  const handleSend = useCallback(async (message: string) => {
    if (!id) return
    counterRef.current += 1
    const now = new Date()
    const ts = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
    const userHtml = `<div class="prose-row prose-user"><div class="prose-avatar user">Y</div><div class="prose-content"><div class="prose-text">${message.replace(/</g, '&lt;')}</div></div><div class="prose-ts">${ts}</div></div>`
    setEvents(prev => [...prev, { id: counterRef.current, html: userHtml, type: 'message', text: message }])
    await sendMessage(id, message)
  }, [id])

  if (!id) return null
  const isDriving = mode === 'assistant'

  return (
    <div className="focus-view">
      {/* Left sidebar */}
      <div className="focus-left">
        <button className="btn btn-ghost" onClick={() => navigate('/')} style={{ alignSelf: 'flex-start', marginBottom: 8 }}>← Back</button>
        <div><div className="stat-label">Status</div><div className="stat-value"><span style={{ color: agent?.running ? 'var(--running)' : 'var(--muted)' }}>{agent?.running ? '● running' : '○ idle'}</span></div></div>
        <div><div className="stat-label">Mode</div><div className="stat-value">{mode}</div></div>
        <div><div className="stat-label">Agent</div><div className="stat-value" style={{ fontSize: 11 }}>{id}</div></div>
        {agent?.task_id && <div><div className="stat-label">Task</div><div className="stat-value" style={{ fontSize: 12 }}>{agent.task_id}</div></div>}
      </div>

      {/* Center — event stream */}
      <div className="focus-center">
        <div className="agent-header">
          <button className="back-btn" onClick={() => navigate('/')}>←</button>
          <div className="agent-id"><strong>{id}</strong></div>
          <span className={`mode-pill ${isDriving ? 'assumed' : ''}`} id="mode-pill"><span className="pill-dot" />{isDriving ? 'driving' : 'watching'}</span>
          <div className="spacer" />
          {isDriving ? <button className="btn btn-relinquish" onClick={handleRelinquish}>Relinquish</button> : <button className="btn btn-assume" onClick={handleAssume}>Assume</button>}
        </div>
        <div className="focus-events" id="focus-events">
          {events.length === 0 && <p style={{ color: 'var(--muted)', fontSize: 12, padding: 10 }}>Waiting for events...</p>}
          {events.map(evt => <div key={evt.id} dangerouslySetInnerHTML={{ __html: evt.html }} />)}
          <div ref={eventsEndRef} />
        </div>
        <ChatInput onSend={handleSend} disabled={!agent} />
      </div>

      {/* Right panel — tabbed */}
      <div className="focus-right" style={{ display: 'flex', flexDirection: 'column', padding: 0 }}>
        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          {(['terminal', 'review', 'browser'] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              flex: 1, padding: '8px 4px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
              letterSpacing: 0.5, border: 0, cursor: 'pointer', fontFamily: 'inherit',
              background: tab === t ? 'var(--surface-raised)' : 'transparent',
              color: tab === t ? 'var(--fg)' : 'var(--muted)',
              borderBottom: tab === t ? '2px solid var(--info)' : '2px solid transparent',
            }}>
              {t === 'terminal' ? '▶ Terminal' : t === 'review' ? '📋 Review' : '🌐 Browser'}
            </button>
          ))}
        </div>

        {/* Panel content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: tab !== 'terminal' ? 12 : 0 }}>
          {tab === 'terminal' && <TerminalPanel lines={termLines} endRef={termEndRef} agent={agent} />}
          {tab === 'review' && <ReviewPanel task={task} agent={agent} />}
          {tab === 'browser' && <BrowserPanel />}
        </div>
      </div>
    </div>
  )
}

// ── Terminal Panel ──────────────────────────────────────────────────────────

function TerminalPanel({ lines, endRef, agent }: { lines: string[]; endRef: React.RefObject<HTMLDivElement | null>; agent: AgentInfo | null }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'oklch(7% 0.003 260)' }}>
      <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--muted-2)', borderBottom: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)' }}>
        {agent?.running ? '● session active' : '○ session idle'} · {lines.length} lines
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px', fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.6, color: 'var(--fg-soft)' }}>
        {lines.length === 0 && <span style={{ color: 'var(--muted-2)' }}>Waiting for shell output...</span>}
        {lines.map((line, i) => (
          <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', paddingBottom: 2 }}>{line}</div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}

// ── Review Panel ────────────────────────────────────────────────────────────

function ReviewPanel({ task, agent }: { task: TaskDetail | null; agent: AgentInfo | null }) {
  if (!task) {
    return (
      <div style={{ padding: 12 }}>
        <div style={{ fontSize: 13, color: 'var(--fg-soft)', marginBottom: 4 }}>No task assigned</div>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>Start a session from a task card on the board to see review details here.</div>
        {agent?.task_id && (
          <div style={{ marginTop: 8 }}>
            <a href={`#/tasks/${agent.task_id}`} style={{ color: 'var(--info)', fontSize: 12 }}>View task {agent.task_id} →</a>
          </div>
        )}
      </div>
    )
  }

  const stepsDone = task.steps.filter(s => s.status === 'done').length
  const pct = task.steps.length > 0 ? Math.round((stepsDone / task.steps.length) * 100) : 0

  return (
    <div>
      {/* Progress */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>Progress</div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
          <span style={{ color: 'var(--muted)' }}>{task.title}</span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--info)' }}>{pct}%</span>
        </div>
        <div style={{ height: 4, background: 'var(--border)', borderRadius: 99, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: 'var(--info)' }} />
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, fontSize: 11, color: 'var(--muted)' }}>
          <span>✓ {stepsDone} done</span>
          <span>● {task.steps.filter(s => s.status === 'in_progress').length} active</span>
          <span>○ {task.steps.filter(s => !['done', 'in_progress'].includes(s.status)).length} pending</span>
        </div>
      </div>

      {/* Acceptance criteria */}
      {task.acceptance_criteria.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>Criteria</div>
          {task.acceptance_criteria.map((c, i) => (
            <div key={i} style={{ fontSize: 12, color: 'var(--fg-soft)', padding: '3px 0', display: 'flex', gap: 6 }}>
              <span style={{ color: 'var(--muted)' }}>☐</span> {c}
            </div>
          ))}
        </div>
      )}

      {/* Recent progress */}
      {task.progress.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
            Recent ({task.progress.length})
          </div>
          {[...task.progress].reverse().slice(0, 5).map((p, i) => (
            <div key={i} style={{ fontSize: 11, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
              <div style={{ color: 'var(--fg-soft)' }}>{p.entry}</div>
              <div style={{ color: 'var(--muted-2)', marginTop: 2, fontFamily: 'var(--font-mono)', fontSize: 10 }}>{p.status} · {p.caller}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        <a href={`#/tasks/${task.id}`} style={{ color: 'var(--info)', fontSize: 12 }}>Open full task detail →</a>
      </div>
    </div>
  )
}

// ── Browser Panel ───────────────────────────────────────────────────────────

function BrowserPanel() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8 }}>
      <div style={{ fontSize: 32, opacity: 0.3 }}>🌐</div>
      <div style={{ fontSize: 13, color: 'var(--fg-soft)' }}>Browser preview</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center' }}>
        If the agent starts a dev server,<br />the preview will appear here.
      </div>
    </div>
  )
}

function stripHtml(html: string): string {
  const div = document.createElement('div')
  div.innerHTML = html
  return div.textContent || div.innerText || ''
}

export default AgentFocus
