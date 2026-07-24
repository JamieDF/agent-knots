import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  setAutonomous, sendMessage, checkpointAgent, revertAgent, interruptAgent,
  fetchTask, fetchAgent, deleteAgent, type AgentInfo, type TaskDetail,
} from '../../lib/api'
import { subscribeToAgent, type SSEEvent } from '../../lib/sse'
import { Chip, Toggle } from '../../components/primitives'
import ConfirmDialog from '../../components/ConfirmDialog'
import { BrowserPanel } from './BrowserPanel'
import { CommandLogPanel } from './CommandLogPanel'
import { EventRow } from './EventRow'
import { FilesPanel } from './FilesPanel'
import { TerminalPanel } from './TerminalPanel'
import {
  type BrowserTab, type CommandEntry, type EventItem, type FileChange, type Tab,
  newBrowserTabId, recordCommand, recordFileTouch, reduceEvent,
} from './types'

const RAIL_WIDTH_KEY = 'agent-knots-thread-rail-width'
// Bounds are a percentage of the space actually being split between
// chat and rail (the goal rail, if shown, is a separate fixed-width
// panel and isn't part of what this divider divides) — not a fixed
// pixel min/max, so it stays proportionally sane at any window size.
const RAIL_MIN_FRACTION = 0.05
const RAIL_MAX_FRACTION = 0.95
const GOAL_RAIL_WIDTH = 260

/** Agent Thread — the full 3-zone Atelier layout (Phase 3). Header, left
 * goal rail (collapsible via Cmd/Ctrl+B), center event stream with a
 * renderer per event kind, composer with autonomous/paused/ended states,
 * right rail (Terminal/Files/Commands/Browser). See
 * design_handoff_atelier_cockpit/README.md §2. */
function AgentThread() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const eventsEndRef = useRef<HTMLDivElement>(null)
  const counterRef = useRef(0)
  const rowRef = useRef<HTMLDivElement>(null)

  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [collapsedThinks, setCollapsedThinks] = useState<Set<number>>(new Set())
  const [openDelegates, setOpenDelegates] = useState<Set<number>>(new Set())
  const [draft, setDraft] = useState('')
  const [tab, setTab] = useState<Tab>('terminal')
  const [files, setFiles] = useState<FileChange[]>([])
  const [commands, setCommands] = useState<CommandEntry[]>([])
  const [replayPos, setReplayPos] = useState<number | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [browserTabs, setBrowserTabs] = useState<BrowserTab[]>(() => [{ id: newBrowserTabId(), url: '' }])
  const [activeBrowserTabId, setActiveBrowserTabId] = useState(() => browserTabs[0].id)
  const [railWidth, setRailWidth] = useState(() => {
    const stored = Number(localStorage.getItem(RAIL_WIDTH_KEY))
    return stored > 0 && stored < window.innerWidth ? stored : 290
  })
  const [resizing, setResizing] = useState(false)

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
        setEvents(prev => reduceEvent(prev, evt, counterRef.current))

        if (evt.type === 'tool_call' && evt.tool_call) {
          recordFileTouch(evt.tool_call, setFiles)
          recordCommand(evt.tool_call, setCommands)
        }
      },
    )
    return () => es.close()
  }, [id])

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

  // The single Autonomous toggle — only meaningful for a task-attached
  // session (there's no task to self-direct from otherwise). Turning it
  // off is the "hold up" action: interrupts whatever's running right now
  // and stops the agent from self-continuing. Turning it back on nudges
  // it to resume the task. See SessionManager.set_autonomous().
  const handleToggleAutonomous = useCallback(async (on: boolean) => {
    if (!id) return
    // Optimistic — the mode/composer state otherwise looks unresponsive
    // for up to one 3s poll cycle after clicking, even though the
    // backend already applied it.
    setAgent(prev => prev ? { ...prev, mode: on ? 'agent' : 'assistant' } : prev)
    await setAutonomous(id, on)
  }, [id])
  const handleDelete = useCallback(async () => {
    if (!id) return
    await deleteAgent(id)
    navigate('/')
  }, [id, navigate])
  // Cancels the current turn only — the session stays open (unlike
  // Delete). Only shown while the agent is actually running, since
  // there's nothing to interrupt otherwise.
  const handleInterrupt = useCallback(async () => { if (id) await interruptAgent(id) }, [id])
  const handleSend = useCallback(async () => {
    if (!id || !draft.trim()) return
    const text = draft.trim()
    setDraft('')
    // Sending a message while autonomous is itself the "hold up" — it
    // interrupts whatever's running and pauses self-continuation, no
    // separate toggle-off click required first.
    if (task && agent?.mode === 'agent') {
      setAgent(prev => prev ? { ...prev, mode: 'assistant' } : prev)
      await setAutonomous(id, false)
    }
    await sendMessage(id, text)
  }, [id, draft, agent, task])
  const handleCheckpoint = useCallback(async () => {
    if (!id) return
    const label = window.prompt('Checkpoint label', 'checkpoint') || 'checkpoint'
    await checkpointAgent(id, label)
  }, [id])
  // A URL the agent mentions in chat (e.g. a dev server it just started)
  // opens in a brand-new Browser tab — like clicking a link in a real
  // browser, it doesn't clobber whatever the user already has open there.
  const openInNewBrowserTab = useCallback((url: string) => {
    const id = newBrowserTabId()
    setBrowserTabs(prev => [...prev, { id, url }])
    setActiveBrowserTabId(id)
    setTab('browser')
  }, [])
  const newBrowserTab = useCallback(() => {
    const id = newBrowserTabId()
    setBrowserTabs(prev => [...prev, { id, url: '' }])
    setActiveBrowserTabId(id)
  }, [])
  const closeBrowserTab = useCallback((id: string) => {
    const idx = browserTabs.findIndex(t => t.id === id)
    const next = browserTabs.filter(t => t.id !== id)
    if (next.length === 0) {
      const freshId = newBrowserTabId()
      setBrowserTabs([{ id: freshId, url: '' }])
      setActiveBrowserTabId(freshId)
      return
    }
    setBrowserTabs(next)
    if (activeBrowserTabId === id) {
      const neighbor = next[Math.max(0, idx - 1)] ?? next[0]
      setActiveBrowserTabId(neighbor.id)
    }
  }, [browserTabs, activeBrowserTabId])
  const updateBrowserTabUrl = useCallback((tabId: string, url: string) => {
    setBrowserTabs(prev => prev.map(t => (t.id === tabId ? { ...t, url } : t)))
  }, [])

  // Drag-to-resize the right rail. Tracks the drag with window-level
  // listeners (not React state per mouse-move — that would re-render on
  // every pixel) and only commits to state/localStorage on mouseup, via
  // a ref holding the live width during the drag. Min/max are computed
  // fresh at drag-start from the row's actual current width, so they
  // stay correct across window resizes rather than baking in stale
  // pixel bounds from whenever the component first mounted.
  const dragRef = useRef<{ startX: number; startWidth: number; minWidth: number; maxWidth: number } | null>(null)
  const railWidthRef = useRef(railWidth)
  railWidthRef.current = railWidth

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const rowWidth = rowRef.current?.getBoundingClientRect().width ?? window.innerWidth
    const goalRailWidth = task && !railCollapsed ? GOAL_RAIL_WIDTH : 0
    const splittableWidth = Math.max(0, rowWidth - goalRailWidth)
    dragRef.current = {
      startX: e.clientX,
      startWidth: railWidthRef.current,
      minWidth: splittableWidth * RAIL_MIN_FRACTION,
      maxWidth: splittableWidth * RAIL_MAX_FRACTION,
    }
    setResizing(true)

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return
      const { startX, startWidth, minWidth, maxWidth } = dragRef.current
      const delta = startX - ev.clientX // drag left = wider rail
      const next = Math.min(maxWidth, Math.max(minWidth, startWidth + delta))
      setRailWidth(next)
    }
    const onUp = () => {
      dragRef.current = null
      setResizing(false)
      localStorage.setItem(RAIL_WIDTH_KEY, String(railWidthRef.current))
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [task, railCollapsed])

  if (!id) return null
  // Autonomous only means anything for a task-attached session — there's
  // no task to self-direct from otherwise.
  const isAutonomous = !!task && agent?.mode === 'agent'
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
        {/* The Autonomous toggle — only shown when there's a task to
            self-direct from. Flipping it off is the "hold up" action:
            interrupts whatever's running right now; flipping it back on
            nudges the agent to resume the task. */}
        {task && (
          <div
            title={isAutonomous ? 'Autonomous — working on the task on its own. Turn off to hold up.' : 'Paused — reply below, or turn Autonomous back on to resume the task.'}
            style={{ display: 'flex', alignItems: 'center', gap: 7 }}
          >
            <Toggle checked={isAutonomous} onChange={handleToggleAutonomous} small />
            <span style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.05em', color: isAutonomous ? 'var(--acc)' : 'var(--mut)' }}>
              {isAutonomous ? '⚡ AUTONOMOUS' : '⏸ PAUSED'}
            </span>
          </div>
        )}
        {agent?.model && <Chip mono>{agent.model}</Chip>}
        {task && <button onClick={() => setRailCollapsed(r => !r)} title="Toggle rail (⌘B)" style={{ fontSize: 11, color: 'var(--mut)', fontFamily: 'var(--font-mono)' }}>⌘B</button>}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>
            {agent?.tokens_used.toLocaleString() ?? 0} tok · ${agent?.cost_usd.toFixed(3) ?? '0.000'} · {uptime}
          </span>
          <button onClick={() => setConfirmDelete(true)} title="Delete this session" style={pillBtn('var(--card2)', 'var(--err)')}>✕ Delete</button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this session?"
        message="This ends the agent and removes its thread — this cannot be undone."
        confirmLabel="Delete"
        danger
        onConfirm={() => { setConfirmDelete(false); handleDelete() }}
        onCancel={() => setConfirmDelete(false)}
      />

      <div ref={rowRef} style={{ flex: 1, display: 'flex', overflow: 'hidden', userSelect: resizing ? 'none' : undefined }}>
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
                onOpenPreview={openInNewBrowserTab}
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
          ) : (
            <div style={{ borderTop: '1px solid var(--line)', background: 'var(--card)' }}>
              {/* A banner, not a locked composer — typing below and
                  hitting Send is itself the "hold up" that pauses
                  Autonomous, so there's no separate toggle-off step
                  required. Only shown while actually autonomous —
                  paused/no-task sessions are just a normal chat. */}
              {isAutonomous && (
                <div style={{ padding: '6px 20px', fontSize: 12, color: 'var(--mut)', background: 'var(--card2)', borderBottom: '1px solid var(--line)' }}>
                  ⚡ Working autonomously on the task. Type a message anytime to step in.
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, padding: 12 }}>
                <input
                  value={draft} onChange={e => setDraft(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleSend() }}
                  placeholder={isAutonomous ? 'Type to step in…' : 'Message the agent…'}
                  style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--line2)', background: 'var(--card2)', color: 'var(--ink)', fontSize: 13, outline: 'none' }}
                />
                <button onClick={handleSend} style={{ padding: '8px 16px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}>Send</button>
                <button onClick={handleCheckpoint} title="Checkpoint" style={{ padding: '8px 12px', borderRadius: 8, fontSize: 13, color: 'var(--mut)', background: 'var(--card2)' }}>⚑</button>
                {/* Only shown while the agent is actually running — cancels
                    the current turn only, session stays open (type + Send
                    to continue), unlike Delete in the header. */}
                {agent?.running && (
                  <button onClick={handleInterrupt} title="Cancel the agent's current action — the session stays open, send another message to continue" style={pillBtn('var(--card2)', 'var(--ink2)')}>■ Stop</button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Drag handle — resizes the right rail. A few px of invisible
            hit-area around a thinner visible line, so it's easy to grab
            without needing pixel-perfect precision. */}
        <div
          onMouseDown={handleResizeStart}
          title="Drag to resize"
          style={{
            width: 9, marginLeft: -4, marginRight: -5, flexShrink: 0, cursor: 'col-resize',
            position: 'relative', zIndex: 1,
          }}
        >
          <div style={{
            position: 'absolute', left: 4, top: 0, bottom: 0, width: 1,
            background: resizing ? 'var(--acc)' : 'transparent',
          }} />
        </div>

        {/* Right rail */}
        <div style={{ width: railWidth, flexShrink: 0, display: 'flex', flexDirection: 'column', borderLeft: '1px solid var(--line)', background: 'var(--card)' }}>
          <div style={{ display: 'flex', borderBottom: '1px solid var(--line)' }}>
            {(['terminal', 'files', 'commands', 'browser'] as Tab[]).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex: 1, padding: '8px 4px', fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
                color: tab === t ? 'var(--ink)' : 'var(--mut)',
                borderBottom: tab === t ? '2px solid var(--acc)' : '2px solid transparent',
              }}>{t}</button>
            ))}
          </div>
          <div style={{ flex: 1, position: 'relative' }}>
            {/* Terminal stays mounted continuously (just hidden) rather
                than mounting/unmounting with the other tabs — its
                websocket carries real shell state (cwd, exported vars,
                a still-running command) that switching to Files and
                back shouldn't blow away. */}
            <div style={{ position: 'absolute', inset: 0, display: tab === 'terminal' ? 'block' : 'none' }}>
              <TerminalPanel agentId={id} active={tab === 'terminal'} />
            </div>
            {tab !== 'terminal' && (
              <div style={{ position: 'absolute', inset: 0, overflowY: 'auto' }}>
                {tab === 'files' && <FilesPanel files={files} agentId={id} />}
                {tab === 'commands' && <CommandLogPanel commands={commands} />}
                {tab === 'browser' && (
                  <BrowserPanel
                    tabs={browserTabs}
                    activeTabId={activeBrowserTabId}
                    onSelectTab={setActiveBrowserTabId}
                    onCloseTab={closeBrowserTab}
                    onNewTab={newBrowserTab}
                    onUrlChange={updateBrowserTabUrl}
                  />
                )}
              </div>
            )}
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

export default AgentThread
