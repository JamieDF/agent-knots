import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  assumeAgent, relinquishAgent, sendMessage, checkpointAgent, revertAgent,
  fetchTask, fetchAgent, deleteAgent, type AgentInfo, type TaskDetail,
} from '../lib/api'
import { subscribeToAgent, type SSEEvent } from '../lib/sse'
import { Chip } from '../components/primitives'
import Markdown from '../components/Markdown'

interface EventItem extends SSEEvent { id: number; result?: SSEEvent }
type Tab = 'terminal' | 'files' | 'preview'

interface FileChange { path: string; action: string; timestamp: number }

/** Agent Thread — the full 3-zone Atelier layout (Phase 3). Header, left
 * goal rail (collapsible via Cmd/Ctrl+B), center event stream with a
 * renderer per event kind, composer with driving/watching/ended states,
 * right rail (Terminal/Files/Preview). See
 * design_handoff_atelier_cockpit/README.md §2. */
function AgentThread() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const eventsEndRef = useRef<HTMLDivElement>(null)
  const counterRef = useRef(0)

  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [collapsedThinks, setCollapsedThinks] = useState<Set<number>>(new Set())
  const [openDelegates, setOpenDelegates] = useState<Set<number>>(new Set())
  const [draft, setDraft] = useState('')
  const [tab, setTab] = useState<Tab>('terminal')
  const [termLines, setTermLines] = useState<string[]>([])
  const [files, setFiles] = useState<FileChange[]>([])
  const [replayPos, setReplayPos] = useState<number | null>(null)

  const ended = useMemo(() => events.some(e => e.type === 'ended'), [events])

  // Poll agent + task (mode/tokens/cost/running aren't carried on SSE).
  useEffect(() => {
    if (!id) return
    let mounted = true
    const poll = async () => {
      try {
        const a = await fetchAgent(id)
        if (!mounted) return
        setAgent(a)
        if (a.task_id) fetchTask(a.task_id).then(t => { if (mounted) setTask(t) }).catch(() => {})
      } catch { /* agent may have been deleted */ }
    }
    poll()
    const interval = setInterval(poll, 3000)
    return () => { mounted = false; clearInterval(interval) }
  }, [id])

  // SSE subscription.
  useEffect(() => {
    if (!id) return
    const es = subscribeToAgent(
      id,
      (evt: SSEEvent) => {
        counterRef.current += 1
        setEvents(prev => {
          // A tool call streams in incrementally — the backend re-emits
          // the whole tool_call event (same id) as its args accumulate
          // (e.g. empty args, then partially parsed, then complete).
          // Update the existing card in place instead of appending a new
          // one each time, or every tool call would render as 2-3
          // duplicate cards.
          if (evt.type === 'tool_call' && evt.tool_call) {
            const callId = evt.tool_call.id
            for (let i = prev.length - 1; i >= 0; i--) {
              if (prev[i].type === 'tool_call' && prev[i].tool_call?.id === callId) {
                const next = [...prev]
                next[i] = { ...next[i], tool_call: evt.tool_call, timestamp: evt.timestamp }
                return next
              }
            }
          }
          // Merge tool_result into the most recent unresolved tool_call
          // (tool_call_id linkage isn't reliably populated backend-side
          // yet, so this merges by adjacency instead — a deliberate
          // approximation, see events.py::TOOL_RESULT construction).
          if (evt.type === 'tool_result') {
            for (let i = prev.length - 1; i >= 0; i--) {
              if (prev[i].type === 'tool_call' && !prev[i].result) {
                const next = [...prev]
                next[i] = { ...next[i], result: evt }
                return next
              }
            }
          }
          // message/thinking stream in as many small text deltas, each
          // its own event — appending each as a separate bubble produced
          // a dozen tiny fragments per turn instead of one bubble that
          // grows, which also broke markdown that spans a fragment
          // boundary (a "**bold**" split across two deltas renders as
          // literal asterisks in each half instead of one bold run).
          // Accumulate consecutive same-type text into the prior bubble.
          if ((evt.type === 'message' || evt.type === 'thinking') && prev.length > 0) {
            const last = prev[prev.length - 1]
            if (last.type === evt.type) {
              const next = [...prev]
              next[next.length - 1] = { ...last, message: (last.message || '') + (evt.message || ''), timestamp: evt.timestamp }
              return next
            }
          }
          return [...prev.slice(-300), { ...evt, id: counterRef.current }]
        })

        if (evt.type === 'tool_call' && evt.tool_call) {
          const path = findFilePath(evt.tool_call.args)
          if (path) {
            const name = evt.tool_call.name.toLowerCase()
            const action = name.includes('edit') || name.includes('write') ? 'edit'
              : name.includes('shell') || name.includes('bash') ? 'shell' : 'read'
            setFiles(prev => prev.find(f => f.path === path) ? prev : [...prev.slice(-50), { path, action, timestamp: Date.now() }])
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

  // Terminal lines derived from tool_result messages (kept separate from
  // the merged event stream since Terminal shows raw output history).
  useEffect(() => {
    const last = events[events.length - 1]
    if (last?.type === 'tool_call' && last.result?.message) {
      setTermLines(prev => [...prev.slice(-500), last.result!.message])
    }
  }, [events])

  useEffect(() => {
    if (replayPos === null) eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events, replayPos])

  // Cmd/Ctrl+B toggles the goal rail.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') { e.preventDefault(); setRailCollapsed(r => !r) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const handleAssume = useCallback(async () => {
    if (!id) return
    // Optimistic — the mode/composer state otherwise looks unresponsive
    // for up to one 3s poll cycle after clicking, even though the
    // backend already applied it.
    setAgent(prev => prev ? { ...prev, mode: 'assistant' } : prev)
    await assumeAgent(id)
  }, [id])
  const handleRelinquish = useCallback(async () => {
    if (!id) return
    setAgent(prev => prev ? { ...prev, mode: 'agent' } : prev)
    await relinquishAgent(id)
  }, [id])
  const handleStop = useCallback(async () => { if (id) await deleteAgent(id) }, [id])
  const handleDelete = useCallback(async () => {
    if (!id) return
    if (!window.confirm('Delete this session? This ends the agent and removes its thread — this cannot be undone.')) return
    await deleteAgent(id)
    navigate('/')
  }, [id, navigate])
  const handleSend = useCallback(async () => {
    if (!id || !draft.trim()) return
    await sendMessage(id, draft.trim())
    setDraft('')
  }, [id, draft])
  const handleCheckpoint = useCallback(async () => {
    if (!id) return
    const label = window.prompt('Checkpoint label', 'checkpoint') || 'checkpoint'
    await checkpointAgent(id, label)
  }, [id])

  if (!id) return null
  const isDriving = agent?.mode === 'assistant'
  const visibleEvents = replayPos !== null ? events.slice(0, replayPos) : events
  const uptime = agent ? formatUptime(Date.now() / 1000 - agent.started_at) : ''

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, margin: '0 10px 10px',
      background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 12,
      boxShadow: 'var(--shadow)', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderBottom: '1px solid var(--line)', background: 'var(--card)', flexShrink: 0 }}>
        <button onClick={() => navigate('/')} style={{ fontSize: 16, color: 'var(--ink2)' }}>←</button>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: agent?.running ? 'var(--ok)' : 'var(--mut2)' }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{task?.title || id}</span>
        <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>{id}</span>
        <Chip color={isDriving ? 'var(--warn-ink)' : 'var(--mut)'} soft>{isDriving ? 'DRIVING' : 'WATCHING'}</Chip>
        {agent?.model && <Chip mono>{agent.model}</Chip>}
        {task && <button onClick={() => setRailCollapsed(r => !r)} title="Toggle rail (⌘B)" style={{ fontSize: 11, color: 'var(--mut)', fontFamily: 'var(--font-mono)' }}>⌘B</button>}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>
            {agent?.tokens_used.toLocaleString() ?? 0} tok · ${agent?.cost_usd.toFixed(3) ?? '0.000'} · {uptime}
          </span>
          {isDriving
            ? <button onClick={handleRelinquish} style={pillBtn('var(--acc-soft)', 'var(--acc)')}>Relinquish</button>
            : <button onClick={handleAssume} style={pillBtn('var(--warn-soft)', 'var(--warn-ink)')}>Assume</button>}
          <button onClick={handleStop} title="Stop the agent" style={pillBtn('var(--card2)', 'var(--ink2)')}>■ Stop</button>
          <button onClick={handleDelete} title="Delete this session" style={pillBtn('var(--card2)', 'var(--err)')}>✕</button>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left goal rail — only for sessions with a task attached. An
            unattached session has nothing to show here, so skip the rail
            entirely rather than rendering an empty "no task" column; the
            center thread gets the full width instead. */}
        {task && !railCollapsed && (
          <div style={{ width: 260, flexShrink: 0, background: 'var(--card2)', borderRight: '1px solid var(--line)', padding: 16, overflowY: 'auto' }}>
            <SectionHeading>Goal</SectionHeading>
            <Link to={`/tasks/${task.id}`} style={{ fontSize: 13, fontWeight: 600, color: 'var(--acc)', display: 'block', marginBottom: 6 }}>{task.title}</Link>
            {task.description && <div style={{ fontSize: 12, color: 'var(--ink2)', lineHeight: 1.5, marginBottom: 16 }}>{task.description}</div>}

            {task.steps.length > 0 && (
              <>
                <SectionHeading>Steps</SectionHeading>
                {(() => {
                  const done = task.steps.filter(s => s.status === 'done').length
                  const pct = Math.round((done / task.steps.length) * 100)
                  return (
                    <>
                      <div style={{ height: 4, background: 'var(--line)', borderRadius: 99, marginBottom: 8, overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${pct}%`, background: 'var(--acc)' }} />
                      </div>
                      {task.steps.map(s => (
                        <div key={s.id} style={{ fontSize: 12, color: s.status === 'done' ? 'var(--mut)' : 'var(--ink2)', textDecoration: s.status === 'done' ? 'line-through' : undefined, marginBottom: 4 }}>
                          {s.status === 'done' ? '✓' : '○'} {s.title}
                        </div>
                      ))}
                    </>
                  )
                })()}
              </>
            )}

            {task.acceptance_criteria.length > 0 && (
              <>
                <SectionHeading>Criteria</SectionHeading>
                {task.acceptance_criteria.map((c, i) => {
                  const met = task.criteria_met.includes(c)
                  return <div key={i} style={{ fontSize: 12, color: met ? 'var(--mut)' : 'var(--ink2)', marginBottom: 4 }}>{met ? '✓' : '○'} {c}</div>
                })}
              </>
            )}
          </div>
        )}

        {/* Center thread */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 20px' }}>
            {visibleEvents.length === 0 && <div style={{ fontSize: 12, color: 'var(--mut)', padding: 10 }}>Waiting for events…</div>}
            {visibleEvents.map(evt => (
              <EventRow
                key={evt.id}
                evt={evt}
                collapsed={collapsedThinks.has(evt.id)}
                onToggleCollapse={() => setCollapsedThinks(s => toggle(s, evt.id))}
                delegateOpen={openDelegates.has(evt.id)}
                onToggleDelegate={() => setOpenDelegates(s => toggle(s, evt.id))}
                onRevert={label => id && revertAgent(id, label)}
              />
            ))}
            <div ref={eventsEndRef} />
          </div>

          {/* Composer */}
          {ended ? (
            <div style={{ padding: '12px 20px', borderTop: '1px solid var(--line)', background: 'var(--card)' }}>
              <input
                type="range" min={0} max={events.length} value={replayPos ?? events.length}
                onChange={e => setReplayPos(Number(e.target.value))}
                style={{ width: '100%', marginBottom: 6 }}
              />
              <div style={{ fontSize: 11.5, color: 'var(--mut)', textAlign: 'center' }}>session ended{replayPos !== null && replayPos < events.length ? ` — replaying ${replayPos}/${events.length}` : ''}</div>
            </div>
          ) : isDriving ? (
            <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid var(--line)', background: 'var(--card)' }}>
              <input
                value={draft} onChange={e => setDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSend() }}
                placeholder="Message the agent…"
                style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--line2)', background: 'var(--card2)', color: 'var(--ink)', fontSize: 13, outline: 'none' }}
              />
              <button onClick={handleSend} style={{ padding: '8px 16px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}>Send</button>
              <button onClick={handleCheckpoint} title="Checkpoint" style={{ padding: '8px 12px', borderRadius: 8, fontSize: 13, color: 'var(--mut)', background: 'var(--card2)' }}>⚑</button>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 12, borderTop: '1px solid var(--line)', background: 'var(--card2)' }}>
              <span style={{ fontSize: 12.5, color: 'var(--mut)', flex: 1 }}>👁 Watching — the agent is driving. Assume control to send messages.</span>
              <button onClick={handleAssume} style={pillBtn('var(--warn-soft)', 'var(--warn-ink)')}>Assume</button>
            </div>
          )}
        </div>

        {/* Right rail */}
        <div style={{ width: 290, flexShrink: 0, display: 'flex', flexDirection: 'column', borderLeft: '1px solid var(--line)', background: 'var(--card)' }}>
          <div style={{ display: 'flex', borderBottom: '1px solid var(--line)' }}>
            {(['terminal', 'files', 'preview'] as Tab[]).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex: 1, padding: '8px 4px', fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
                color: tab === t ? 'var(--ink)' : 'var(--mut)',
                borderBottom: tab === t ? '2px solid var(--acc)' : '2px solid transparent',
              }}>{t}</button>
            ))}
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {tab === 'terminal' && <TerminalPanel lines={termLines} running={!!agent?.running} />}
            {tab === 'files' && <FilesPanel files={files} />}
            {tab === 'preview' && <PreviewPanel />}
          </div>
        </div>
      </div>
    </div>
  )
}

function pillBtn(bg: string, color: string): React.CSSProperties {
  return { padding: '5px 12px', borderRadius: 8, fontSize: 12, fontWeight: 600, background: bg, color }
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--mut)', marginTop: 14, marginBottom: 8 }}>{children}</div>
}

function toggle(s: Set<number>, id: number): Set<number> {
  const next = new Set(s)
  if (next.has(id)) next.delete(id); else next.add(id)
  return next
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h ${m % 60}m`
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

// ── Event row ────────────────────────────────────────────────────────────────

function EventRow({ evt, collapsed, onToggleCollapse, delegateOpen, onToggleDelegate, onRevert }: {
  evt: EventItem
  collapsed: boolean
  onToggleCollapse: () => void
  delegateOpen: boolean
  onToggleDelegate: () => void
  onRevert: (label: string) => void
}) {
  const ts = new Date(evt.timestamp * 1000)
  const tsStr = `${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}`

  if (evt.type === 'message') {
    return (
      <Bubble align="left" bg="var(--card2)" ts={tsStr}>
        <Markdown>{evt.message}</Markdown>
      </Bubble>
    )
  }

  if (evt.type === 'thinking') {
    return (
      <div onClick={onToggleCollapse} style={{ padding: '4px 0', cursor: 'pointer' }}>
        <span style={{ fontSize: 12.5, fontStyle: 'italic', color: 'var(--mut)' }}>
          {collapsed ? '⋯ thinking — click to expand' : `⋯ ${evt.message}`}
        </span>
      </div>
    )
  }

  if (evt.type === 'tool_call' && evt.tool_call) {
    const args = Object.entries(evt.tool_call.args).map(([k, v]) => `${k}=${truncate(String(v), 60)}`).join(', ')
    return (
      <div data-testid="tool-card" style={{ margin: '6px 0 6px 36px', background: 'var(--card2)', border: '1px solid var(--line)', borderRadius: 8, padding: '8px 10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: args ? 4 : 0 }}>
          <span style={{ width: 16, height: 16, borderRadius: 4, background: 'var(--card)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: 'var(--acc)' }}>$</span>
          <span style={{ fontSize: 11.5, fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--ink2)' }}>{evt.tool_call.name}</span>
        </div>
        {args && <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)', whiteSpace: 'pre-wrap' }}>{args}</div>}
        {evt.result && <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ok)', marginTop: 4, whiteSpace: 'pre-wrap' }}>{truncate(evt.result.message, 300)}</div>}
      </div>
    )
  }

  if (evt.type === 'auto_log') {
    return <div style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--mut2)', padding: '2px 0 2px 36px' }}>↳ {evt.message}</div>
  }

  if (evt.type === 'steer') {
    return (
      <div style={{ fontSize: 12, fontStyle: 'italic', color: 'var(--acc)', background: 'var(--acc-soft)', padding: '6px 10px', margin: '4px 0 4px 36px', borderRadius: 8 }}>
        ⌁ {evt.message}
      </div>
    )
  }

  if (evt.type === 'delegate') {
    const subId = evt.data?.sub_session_id as string | undefined
    const subTitle = evt.data?.title as string | undefined
    return (
      <div style={{ margin: '8px 0', border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden' }}>
        <div onClick={onToggleDelegate} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', background: 'var(--card2)' }}>
          <span style={{ fontSize: 10 }}>{delegateOpen ? '▾' : '▸'}</span>
          <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.04em', color: 'var(--acc)' }}>SUB-AGENT</span>
          <span style={{ fontSize: 12, color: 'var(--ink2)' }}>{subTitle || evt.message}</span>
          {subId && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--mut)', marginLeft: 'auto' }}>{subId}</span>}
        </div>
        {delegateOpen && subId && <DelegateSubThread sessionId={subId} />}
      </div>
    )
  }

  if (evt.type === 'checkpoint') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '10px 0', paddingTop: 10, borderTop: '1px dashed var(--line2)' }}>
        <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>⚑ checkpoint · {evt.message}</span>
        <button onClick={() => onRevert(evt.message)} style={{ fontSize: 10.5, color: 'var(--acc)', fontWeight: 600 }}>revert to here</button>
      </div>
    )
  }

  if (evt.type === 'blocker' || evt.type === 'ask') {
    return (
      <Bubble align="left" bg="var(--warn-soft)" ts={tsStr}>
        <Markdown>{evt.message}</Markdown>
      </Bubble>
    )
  }

  if (evt.type === 'user') {
    return (
      <Bubble align="right" bg="var(--acc-soft)" ts={tsStr}>
        <Markdown>{evt.message}</Markdown>
      </Bubble>
    )
  }

  if (evt.type === 'error') {
    return (
      <Bubble align="left" ts={tsStr}>
        <span style={{ fontSize: 13, color: 'var(--err)' }}>{evt.error || evt.message}</span>
      </Bubble>
    )
  }

  if (evt.type === 'ended') {
    return <div style={{ textAlign: 'center', fontSize: 11.5, color: 'var(--mut)', padding: '12px 0', borderTop: '1px solid var(--line)', margin: '8px 0' }}>session ended</div>
  }

  // state_change / default — subtle info line.
  return <div style={{ fontSize: 11.5, color: 'var(--mut)', padding: '4px 0 4px 36px' }}>{evt.message}</div>
}

/** Chat-turn layout: agent on the left, human ("user" events) on the
 * right, like any real chat — no avatar, just alignment + a small
 * timestamp under the bubble. */
function Bubble({ align, bg, ts, children }: { align: 'left' | 'right'; bg?: string; ts: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: align === 'right' ? 'flex-end' : 'flex-start', padding: '4px 0' }}>
      <div style={{ maxWidth: '78%', padding: bg ? '8px 12px' : 0, borderRadius: 12, background: bg }}>
        {children}
      </div>
      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--mut2)', marginTop: 3, padding: bg ? '0 3px' : 0 }}>{ts}</div>
    </div>
  )
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 3) + '...' : s
}

// ── Delegation nested sub-thread ─────────────────────────────────────────────

/** Delegation cards expand into their own live mini-thread by opening a
 * separate SSE subscription to the sub-session — no server-side event
 * nesting, reusing the same infra as the top-level thread. */
function DelegateSubThread({ sessionId }: { sessionId: string }) {
  const [events, setEvents] = useState<EventItem[]>([])
  const counterRef = useRef(0)

  useEffect(() => {
    const es = subscribeToAgent(sessionId, (evt: SSEEvent) => {
      counterRef.current += 1
      setEvents(prev => [...prev.slice(-100), { ...evt, id: counterRef.current }])
    })
    return () => es.close()
  }, [sessionId])

  return (
    <div style={{ padding: '8px 12px 8px 24px', borderTop: '1px solid var(--line)' }}>
      {events.length === 0 && <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>Waiting for sub-agent events…</div>}
      {events.map(evt => (
        <div key={evt.id} style={{ fontSize: 11.5, color: 'var(--ink2)', padding: '3px 0' }}>
          {evt.type === 'message' || evt.type === 'thinking' ? evt.message : `[${evt.type}] ${evt.message || ''}`}
        </div>
      ))}
    </div>
  )
}

// ── Right rail panels ────────────────────────────────────────────────────────

function TerminalPanel({ lines, running }: { lines: string[]; running: boolean }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView() }, [lines])
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--mut)', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)' }}>
        {running ? '● active' : '○ idle'} · {lines.length} lines
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 10, fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.6, color: 'var(--ink2)' }}>
        {lines.length === 0 && <span style={{ color: 'var(--mut)' }}>Waiting for shell output...</span>}
        {lines.map((l, i) => <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{l}</div>)}
        <div ref={endRef} />
      </div>
    </div>
  )
}

function FilesPanel({ files }: { files: FileChange[] }) {
  const colors: Record<string, string> = { edit: 'var(--warn-ink)', write: 'var(--warn-ink)', read: 'var(--acc)', shell: 'var(--mut)' }
  const letters: Record<string, string> = { edit: 'M', write: 'A', read: 'R', shell: '$' }
  return (
    <div>
      <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--mut)', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)' }}>{files.length} file{files.length !== 1 ? 's' : ''} touched</div>
      {files.length === 0 && <div style={{ padding: 12, fontSize: 12, color: 'var(--mut)' }}>Files the agent reads or edits will appear here.</div>}
      {files.map((f, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--line)', fontSize: 11 }}>
          <span style={{ width: 16, height: 16, borderRadius: 3, display: 'grid', placeItems: 'center', fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono)', color: colors[f.action] || 'var(--mut)', background: 'var(--card2)' }}>{letters[f.action] || '·'}</span>
          <span style={{ flex: 1, fontFamily: 'var(--font-mono)', color: 'var(--ink2)', wordBreak: 'break-all' }}>{f.path}</span>
        </div>
      ))}
    </div>
  )
}

function PreviewPanel() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, padding: 20, textAlign: 'center' }}>
      <div style={{ fontSize: 28, opacity: 0.3 }}>🌐</div>
      <div style={{ fontSize: 13, color: 'var(--ink2)' }}>Preview</div>
      <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>If the agent starts a dev server, a proxied preview will appear here.</div>
    </div>
  )
}

export default AgentThread
