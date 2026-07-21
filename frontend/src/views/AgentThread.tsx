import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ChatInput from '../components/ChatInput'
import { assumeAgent, relinquishAgent, sendMessage, fetchTask, type AgentInfo, fetchAgents, type TaskDetail } from '../lib/api'
import { subscribeToAgent, type SSEEvent } from '../lib/sse'

interface EventItem extends SSEEvent { id: number }
type Tab = 'terminal' | 'review' | 'code' | 'browser'

interface FileChange {
  path: string
  action: string  // 'read', 'write', 'edit', 'shell'
  timestamp: number
}

/** Interim Agent Thread renderer — Phase 0 only wires the SSE payload
 * from HTML fragments to structured JSON events (see lib/sse.ts); the
 * full 3-zone Atelier layout with per-kind event renderers, delegation
 * expand, checkpoint/revert, and replay scrubber lands in Phase 3. This
 * keeps the same panels/classes as before, just driven by real fields
 * instead of parsing rendered HTML. */
function AgentThread() {
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
  const [files, setFiles] = useState<FileChange[]>([])
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

  // Subscribe to SSE — also extract terminal output + touched files from
  // the structured event fields (no more HTML scraping).
  useEffect(() => {
    if (!id) return
    const es = subscribeToAgent(
      id,
      (evt: SSEEvent) => {
        counterRef.current += 1
        setEvents(prev => [...prev.slice(-200), { ...evt, id: counterRef.current }])

        if (evt.type === 'tool_result' && evt.message) {
          setTermLines(prev => [...prev.slice(-500), evt.message])
        }

        if (evt.type === 'tool_call' && evt.tool_call) {
          const path = findFilePath(evt.tool_call.args)
          if (path) {
            const name = evt.tool_call.name.toLowerCase()
            const action = name.includes('edit') || name.includes('write') ? 'edit'
              : name.includes('shell') || name.includes('bash') ? 'shell'
              : 'read'
            setFiles(prev => {
              if (prev.find(f => f.path === path)) return prev
              return [...prev.slice(-50), { path, action, timestamp: Date.now() }]
            })
          }
        }
      },
      () => {
        counterRef.current += 1
        setEvents(prev => [...prev, {
          id: counterRef.current, type: 'ended', session_id: id, timestamp: Date.now() / 1000,
          message: 'Session ended.', tool_call: null, tool_result: null, error: '', data: null,
        }])
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
    await sendMessage(id, message)
    // The backend now broadcasts a USER event for every sent message
    // (so other viewers see it too) — no need to optimistically render
    // it here ourselves; it'll arrive over the same SSE stream.
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
          {/* DRIVING = user has control (backend mode "assistant"); WATCHING
              = agent has control (backend mode "agent") — see Phase 0 plan's
              terminology note. */}
          <span className={`mode-pill ${isDriving ? 'assumed' : ''}`} id="mode-pill"><span className="pill-dot" />{isDriving ? 'driving' : 'watching'}</span>
          <div className="spacer" />
          {isDriving ? <button className="btn btn-relinquish" onClick={handleRelinquish}>Relinquish</button> : <button className="btn btn-assume" onClick={handleAssume}>Assume</button>}
        </div>
        <div className="focus-events" id="focus-events">
          {events.length === 0 && <p style={{ color: 'var(--muted)', fontSize: 12, padding: 10 }}>Waiting for events...</p>}
          {events.map(evt => <EventRow key={evt.id} evt={evt} />)}
          <div ref={eventsEndRef} />
        </div>
        <ChatInput onSend={handleSend} disabled={!agent} />
      </div>

      {/* Right panel — tabbed */}
      <div className="focus-right" style={{ display: 'flex', flexDirection: 'column', padding: 0 }}>
        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          {(['terminal', 'review', 'code', 'browser'] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              flex: 1, padding: '8px 4px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
              letterSpacing: 0.5, border: 0, cursor: 'pointer', fontFamily: 'inherit',
              background: tab === t ? 'var(--surface-raised)' : 'transparent',
              color: tab === t ? 'var(--fg)' : 'var(--muted)',
              borderBottom: tab === t ? '2px solid var(--info)' : '2px solid transparent',
            }}>
              {t === 'terminal' ? '▶' : t === 'review' ? '📋' : t === 'code' ? '{}' : '🌐'} {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        {/* Panel content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: tab !== 'terminal' ? 12 : 0 }}>
          {tab === 'terminal' && <TerminalPanel lines={termLines} endRef={termEndRef} agent={agent} />}
          {tab === 'review' && <ReviewPanel task={task} agent={agent} />}
          {tab === 'code' && <CodePanel files={files} />}
          {tab === 'browser' && <BrowserPanel />}
        </div>
      </div>
    </div>
  )
}

// ── Event row ────────────────────────────────────────────────────────────────

function EventRow({ evt }: { evt: EventItem }) {
  const ts = new Date(evt.timestamp * 1000)
  const tsStr = `${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}:${String(ts.getSeconds()).padStart(2, '0')}`

  if (evt.type === 'tool_call' && evt.tool_call) {
    const args = Object.entries(evt.tool_call.args)
      .map(([k, v]) => `${k}=${truncate(String(v), 60)}`).join(', ')
    return (
      <div className="tool-card">
        <div className="tool-header"><span className="tool-icon">●</span><span className="tool-name">{evt.tool_call.name}</span></div>
        {args && <div className="tool-args">{args}</div>}
      </div>
    )
  }

  if (evt.type === 'tool_result') {
    return (
      <div className="prose-row">
        <div className="prose-avatar" style={{ color: 'var(--done)' }}>✓</div>
        <div className="prose-content"><div className="prose-text" style={{ color: 'var(--muted)', fontSize: 12 }}>{truncate(evt.message, 200)}</div></div>
        <div className="prose-ts">{tsStr}</div>
      </div>
    )
  }

  if (evt.type === 'thinking') {
    return (
      <div className="prose-row prose-thinking">
        <div className="prose-avatar thinking">T</div>
        <div className="prose-content"><div className="prose-text">{evt.message}</div></div>
        <div className="prose-ts">{tsStr}</div>
      </div>
    )
  }

  if (evt.type === 'blocker' || evt.type === 'ask') {
    return (
      <div className="prose-row prose-blocker">
        <div className="prose-avatar" style={{ color: 'var(--assumed)' }}>?</div>
        <div className="prose-content"><div className="prose-text">{evt.message}</div></div>
        <div className="prose-ts">{tsStr}</div>
      </div>
    )
  }

  if (evt.type === 'error') {
    return (
      <div className="prose-row prose-error">
        <div className="prose-avatar" style={{ color: 'var(--blocked)' }}>!</div>
        <div className="prose-content"><div className="prose-text" style={{ color: 'var(--blocked)' }}>{evt.error || evt.message}</div></div>
        <div className="prose-ts">{tsStr}</div>
      </div>
    )
  }

  if (evt.type === 'user') {
    return (
      <div className="prose-row prose-user">
        <div className="prose-avatar user">Y</div>
        <div className="prose-content"><div className="prose-text">{evt.message}</div></div>
        <div className="prose-ts">{tsStr}</div>
      </div>
    )
  }

  if (evt.type === 'auto_log') {
    return (
      <div style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--muted-2)', padding: '2px 0 2px 34px' }}>
        ↳ {evt.message}
      </div>
    )
  }

  if (evt.type === 'steer') {
    return (
      <div style={{ fontSize: 12, fontStyle: 'italic', color: 'var(--info)', padding: '4px 8px', margin: '4px 0 4px 34px', background: 'oklch(68% 0.12 235 / 0.08)', borderRadius: 6 }}>
        ⌁ {evt.message}
      </div>
    )
  }

  if (evt.type === 'delegate') {
    const subId = evt.data?.sub_session_id as string | undefined
    return (
      <div className="tool-card">
        <div className="tool-header"><span className="tool-icon">◆</span><span className="tool-name">SUB-AGENT: {evt.message}</span></div>
        {subId && <a href={`/agent/${subId}`} style={{ fontSize: 11 }}>Open sub-agent thread →</a>}
      </div>
    )
  }

  if (evt.type === 'checkpoint') {
    return (
      <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--muted)', padding: '8px 0', borderTop: '1px dashed var(--border)', margin: '8px 0' }}>
        ⚑ checkpoint · {evt.message}
      </div>
    )
  }

  if (evt.type === 'ended') {
    return <p style={{ fontSize: 12, color: 'var(--muted)', padding: 10, textAlign: 'center' }}>{evt.message || 'session ended'}</p>
  }

  // message + state_change + default.
  return (
    <div className={`prose-row ${evt.type === 'state_change' ? 'prose-state' : ''}`}>
      <div className="prose-avatar agent">A</div>
      <div className="prose-content"><div className="prose-text" style={evt.type === 'state_change' ? { color: 'var(--muted)', fontSize: 12 } : undefined}>{evt.message}</div></div>
      <div className="prose-ts">{tsStr}</div>
    </div>
  )
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 3) + '...' : s
}

function findFilePath(args: Record<string, unknown>): string | null {
  for (const key of ['path', 'file_path', 'file', 'filepath']) {
    const v = args[key]
    if (typeof v === 'string' && v.length > 0) return v
  }
  for (const v of Object.values(args)) {
    if (typeof v === 'string' && /\.\w{1,8}$/.test(v)) return v
  }
  return null
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
            <a href={`/tasks/${agent.task_id}`} style={{ color: 'var(--info)', fontSize: 12 }}>View task {agent.task_id} →</a>
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
        <a href={`/tasks/${task.id}`} style={{ color: 'var(--info)', fontSize: 12 }}>Open full task detail →</a>
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

// ── Code Panel ─────────────────────────────────────────────────────────────

function CodePanel({ files }: { files: FileChange[] }) {
  const actionColors: Record<string, string> = {
    edit: 'var(--assumed)',
    write: 'var(--assumed)',
    read: 'var(--info)',
    shell: 'var(--muted)',
  }
  const actionIcons: Record<string, string> = {
    edit: 'M',
    write: '+',
    read: '~',
    shell: '$',
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--muted-2)', borderBottom: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)' }}>
        {files.length} file{files.length !== 1 ? 's' : ''} touched
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {files.length === 0 && (
          <div style={{ padding: 12, fontSize: 12, color: 'var(--muted)' }}>
            Files the agent reads or edits will appear here.
          </div>
        )}
        {files.map((f, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px',
            borderBottom: '1px solid var(--border-subtle)', fontSize: 11,
          }}>
            <span style={{
              width: 18, height: 18, borderRadius: 3, display: 'grid', placeItems: 'center',
              fontSize: 10, fontWeight: 600, fontFamily: 'var(--font-mono)',
              background: f.action === 'edit' ? 'oklch(76% 0.16 75 / 0.12)' : f.action === 'read' ? 'oklch(68% 0.12 235 / 0.12)' : 'var(--surface-raised)',
              color: actionColors[f.action] || 'var(--muted)',
              flexShrink: 0,
            }}>{actionIcons[f.action] || '·'}</span>
            <span style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-soft)', wordBreak: 'break-all' }}>{f.path}</span>
            <span style={{ fontSize: 10, color: 'var(--muted-2)', fontFamily: 'var(--font-mono)' }}>
              {new Date(f.timestamp).toLocaleTimeString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AgentThread
