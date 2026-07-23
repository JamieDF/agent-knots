import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  setAutonomous, sendMessage, checkpointAgent, revertAgent, interruptAgent,
  fetchTask, fetchAgent, deleteAgent, fetchAgentFile, type AgentInfo, type TaskDetail,
} from '../lib/api'
import { subscribeToAgent, type SSEEvent } from '../lib/sse'
import { useTheme } from '../theme/ThemeContext'
import { Chip, Toggle } from '../components/primitives'
import Markdown from '../components/Markdown'
import ConfirmDialog from '../components/ConfirmDialog'
import '@xterm/xterm/css/xterm.css'

interface EventItem extends SSEEvent { id: number; result?: SSEEvent }
type Tab = 'terminal' | 'files' | 'commands' | 'browser'

interface BrowserTab { id: string; url: string }

function newBrowserTabId(): string {
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

interface FileChange { path: string; action: string; timestamp: number }
interface CommandEntry { command: string; timestamp: number }

/** Pure event-accumulation reducer, shared by the top-level thread and
 * DelegateSubThread (a delegated sub-agent's nested mini-thread).
 * DelegateSubThread used to append every raw event with no accumulation
 * at all, so a sub-agent's thread rendered as a dozen tiny fragment
 * bubbles and duplicate tool cards even after the top-level thread got
 * fixed for the same problem — sharing this reducer keeps both in sync.
 * Handles three things:
 *  - a tool call streams in incrementally (the backend re-emits the
 *    whole tool_call event, same id, as its args accumulate) — updates
 *    the existing card in place instead of appending a duplicate;
 *  - merges a tool_result into the most recent unresolved tool_call by
 *    adjacency (tool_call_id linkage isn't reliably populated
 *    backend-side yet, see events.py::TOOL_RESULT construction);
 *  - message/thinking stream in as many small text deltas, each its own
 *    event — accumulates consecutive same-type deltas into the prior
 *    bubble instead of a dozen fragments (also needed so markdown
 *    spanning a delta boundary, e.g. "**bold**" split across two
 *    deltas, renders correctly instead of as literal asterisks).
 */
function reduceEvent(prev: EventItem[], evt: SSEEvent, nextId: number, cap = 300): EventItem[] {
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
  if (evt.type === 'tool_result') {
    for (let i = prev.length - 1; i >= 0; i--) {
      if (prev[i].type === 'tool_call' && !prev[i].result) {
        const next = [...prev]
        next[i] = { ...next[i], result: evt }
        return next
      }
    }
  }
  if ((evt.type === 'message' || evt.type === 'thinking') && prev.length > 0) {
    const last = prev[prev.length - 1]
    if (last.type === evt.type) {
      const next = [...prev]
      next[next.length - 1] = { ...last, message: (last.message || '') + (evt.message || ''), timestamp: evt.timestamp }
      return next
    }
  }
  return [...prev.slice(-cap), { ...evt, id: nextId }]
}

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

/** The small status-bar strip at the top of each right-rail panel
 * (Terminal/Files/Commands) — was copy-pasted across all three. */
function PanelHeader({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--mut)', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)' }}>
      {children}
    </div>
  )
}

/** The "nothing here yet" message shown below an empty PanelHeader —
 * same duplication as PanelHeader above. */
function PanelEmptyState({ children }: { children: React.ReactNode }) {
  return <div style={{ padding: 12, fontSize: 12, color: 'var(--mut)' }}>{children}</div>
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

// editor's `command` arg tells us read vs. write — 'view'/'find_line'
// don't touch the file, everything else does (create is a genuinely new
// file, the rest modify an existing one).
const EDITOR_WRITE_COMMANDS = new Set(['create', 'str_replace', 'pattern_replace', 'insert', 'undo_edit'])

/** Only the editor tool belongs on the Files tab — shell commands often
 * reference something that looks like a filename in their args ("cat
 * notes.txt") without it being a real file touch the way an edit/read
 * is, and mixing the two made the tab list commands, not files. */
function recordFileTouch(toolCall: NonNullable<SSEEvent['tool_call']>, setFiles: (fn: (prev: FileChange[]) => FileChange[]) => void) {
  if (toolCall.name !== 'editor') return
  const path = toolCall.args.path
  if (typeof path !== 'string' || !path) return
  const command = typeof toolCall.args.command === 'string' ? toolCall.args.command : ''
  const action = command === 'create' ? 'write' : EDITOR_WRITE_COMMANDS.has(command) ? 'edit' : 'read'
  setFiles(prev => {
    const next = prev.filter(f => f.path !== path)
    return [...next.slice(-49), { path, action, timestamp: Date.now() }]
  })
}

/** Command Log — every shell invocation with its own timestamp, kept
 * separate from Terminal (a real interactive shell) and from Files
 * (editor-only touches). shell's `command` arg can be a single string
 * or a list (parallel commands), so this can log more than one entry
 * per tool call. */
function recordCommand(toolCall: NonNullable<SSEEvent['tool_call']>, setCommands: (fn: (prev: CommandEntry[]) => CommandEntry[]) => void) {
  if (toolCall.name !== 'shell') return
  const raw = toolCall.args.command
  const cmds: string[] = Array.isArray(raw)
    ? raw.map(c => (typeof c === 'string' ? c : (c as Record<string, unknown>)?.command)).filter((c): c is string => typeof c === 'string')
    : typeof raw === 'string' ? [raw] : []
  if (cmds.length === 0) return
  const timestamp = Date.now()
  setCommands(prev => [...prev.slice(-199), ...cmds.map(command => ({ command, timestamp }))])
}

// ── Event row ────────────────────────────────────────────────────────────────

function EventRow({ evt, collapsed, onToggleCollapse, delegateOpen, onToggleDelegate, onRevert, onOpenPreview }: {
  evt: EventItem
  collapsed: boolean
  onToggleCollapse: () => void
  delegateOpen: boolean
  onToggleDelegate: () => void
  onRevert: (label: string) => void
  onOpenPreview: (url: string) => void
}) {
  const ts = new Date(evt.timestamp * 1000)
  const tsStr = `${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}`

  if (evt.type === 'message') {
    return (
      <Bubble align="left" bg="var(--card2)" ts={tsStr}>
        <Markdown onLinkClick={onOpenPreview}>{evt.message}</Markdown>
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
        {evt.result && (
          <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: evt.result.tool_result?.error ? 'var(--err)' : 'var(--ok)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
            {truncate(evt.result.message, 300)}
          </div>
        )}
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
        <Markdown onLinkClick={onOpenPreview}>{evt.message}</Markdown>
      </Bubble>
    )
  }

  if (evt.type === 'user') {
    return (
      <Bubble align="right" bg="var(--acc-soft)" ts={tsStr}>
        <Markdown onLinkClick={onOpenPreview}>{evt.message}</Markdown>
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
      setEvents(prev => reduceEvent(prev, evt, counterRef.current, 100))
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

// xterm.js needs literal colors, not CSS var() references, so these
// mirror index.css's --card/--ink/--acc/--acc-soft tokens directly for
// each theme rather than reading computed style — reading from the DOM
// raced with ThemeProvider's own effect (which sets
// document.body.dataset.theme): React runs child effects before parent
// effects in a commit, and ThemeProvider is an ancestor, so this
// component's effect could fire before the attribute (and the CSS
// cascade depending on it) actually updated.
const TERMINAL_THEMES: Record<'light' | 'dark', { background: string; foreground: string; cursor: string; selectionBackground: string }> = {
  light: { background: '#ffffff', foreground: '#23262b', cursor: '#6c5ce7', selectionBackground: '#f7f5ff' },
  dark: { background: '#23262d', foreground: '#dfe2e8', cursor: '#8f7ff2', selectionBackground: '#2a2740' },
}

/** Real interactive terminal — a PTY-backed shell (agent's own working
 * directory) streamed over a websocket, rendered with xterm.js. Stays
 * mounted for the lifetime of the Agent Thread (see the parent's
 * always-mounted-but-hidden wrapper) so switching tabs doesn't kill the
 * shell's state (cwd, exported vars, a still-running command). */
function TerminalPanel({ agentId, active }: { agentId?: string; active: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<InstanceType<typeof import('@xterm/xterm').Terminal> | null>(null)
  const fitRef = useRef<InstanceType<typeof import('@xterm/addon-fit').FitAddon> | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting')
  const { theme } = useTheme()

  useEffect(() => {
    if (!agentId || !containerRef.current) return
    let disposed = false

    Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]).then(([{ Terminal }, { FitAddon }]) => {
      if (disposed || !containerRef.current) return

      const term = new Terminal({
        fontFamily: '"DM Mono", var(--font-mono), monospace',
        fontSize: 12,
        cursorBlink: true,
        theme: TERMINAL_THEMES[theme],
      })
      const fit = new FitAddon()
      term.loadAddon(fit)
      term.open(containerRef.current)
      try { fit.fit() } catch { /* container may still be 0x0 on first paint */ }
      termRef.current = term
      fitRef.current = fit

      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/api/agent/${agentId}/terminal`)
      wsRef.current = ws

      ws.onopen = () => {
        setStatus('open')
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
      ws.onclose = () => setStatus('closed')
      ws.onerror = () => setStatus('closed')
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'output') term.write(msg.data)
        } catch { /* ignore malformed frames */ }
      }

      const dataDisposable = term.onData(data => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }))
      })

      const resizeObserver = new ResizeObserver(() => {
        if (!active) return // avoid fitting a 0x0 hidden container
        try { fit.fit() } catch { return }
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      })
      resizeObserver.observe(containerRef.current)

      return () => {
        dataDisposable.dispose()
        resizeObserver.disconnect()
        ws.close()
        term.dispose()
      }
    })

    return () => { disposed = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId])

  // The container is 0x0 while display:none (hidden tab) — re-fit once
  // it actually becomes visible, or xterm renders at a stale/wrong size.
  useEffect(() => {
    if (active && fitRef.current && wsRef.current) {
      try { fitRef.current.fit() } catch { return }
      const term = termRef.current
      if (term && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    }
  }, [active])

  // xterm's theme is a snapshot taken once at creation — toggling
  // light/dark afterward otherwise leaves the terminal visually stuck
  // on whichever theme was active when it first connected.
  useEffect(() => {
    if (termRef.current) termRef.current.options.theme = TERMINAL_THEMES[theme]
  }, [theme])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '4px 10px', fontSize: 10, color: 'var(--mut)', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)' }}>
        {status === 'open' ? '● connected' : status === 'connecting' ? '○ connecting…' : '○ disconnected'}
      </div>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, padding: 4 }} />
    </div>
  )
}

interface FileFetch {
  status: 'loading' | 'ready' | 'error'
  content?: string
  truncated?: boolean
  error?: string
}

const MARKDOWN_EXT = /\.(md|markdown)$/i

function FilesPanel({ files, agentId }: { files: FileChange[]; agentId?: string }) {
  const colors: Record<string, string> = { edit: 'var(--warn-ink)', write: 'var(--ok)', read: 'var(--acc)' }
  const letters: Record<string, string> = { edit: 'M', write: 'A', read: 'R' }
  const [expanded, setExpanded] = useState<string | null>(null)
  const [cache, setCache] = useState<Record<string, FileFetch>>({})

  const toggle = (path: string) => {
    if (expanded === path) { setExpanded(null); return }
    setExpanded(path)
    if (!agentId || cache[path]) return
    setCache(prev => ({ ...prev, [path]: { status: 'loading' } }))
    fetchAgentFile(agentId, path)
      .then(res => setCache(prev => ({ ...prev, [path]: { status: 'ready', content: res.content, truncated: res.truncated } })))
      .catch(e => setCache(prev => ({ ...prev, [path]: { status: 'error', error: e instanceof Error ? e.message : 'Failed to load' } })))
  }

  return (
    <div>
      <PanelHeader>{files.length} file{files.length !== 1 ? 's' : ''} touched</PanelHeader>
      {files.length === 0 && <PanelEmptyState>Files the agent reads or edits will appear here.</PanelEmptyState>}
      {files.map((f, i) => {
        const isOpen = expanded === f.path
        const entry = cache[f.path]
        return (
          <div key={i} style={{ borderBottom: '1px solid var(--line)' }}>
            <div
              onClick={() => toggle(f.path)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', fontSize: 11, cursor: 'pointer' }}
            >
              <span style={{ width: 16, height: 16, borderRadius: 3, display: 'grid', placeItems: 'center', fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono)', color: colors[f.action] || 'var(--mut)', background: 'var(--card2)' }}>{letters[f.action] || '·'}</span>
              <span style={{ flex: 1, fontFamily: 'var(--font-mono)', color: 'var(--ink2)', wordBreak: 'break-all' }}>{f.path}</span>
              <span style={{ fontSize: 9, color: 'var(--mut)' }}>{isOpen ? '▾' : '▸'}</span>
            </div>
            {isOpen && (
              <div style={{ padding: '0 10px 10px', background: 'var(--card2)' }}>
                {(!entry || entry.status === 'loading') && <div style={{ fontSize: 11, color: 'var(--mut)', padding: '8px 0' }}>Loading…</div>}
                {entry?.status === 'error' && <div style={{ fontSize: 11, color: 'var(--err)', padding: '8px 0' }}>{entry.error}</div>}
                {entry?.status === 'ready' && (
                  <div style={{ maxHeight: 320, overflowY: 'auto', border: '1px solid var(--line)', borderRadius: 6, background: 'var(--card)', padding: MARKDOWN_EXT.test(f.path) ? '8px 10px' : 0 }}>
                    {entry.truncated && <div style={{ fontSize: 10, color: 'var(--warn-ink)', padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>Truncated — showing the first part of a large file.</div>}
                    {MARKDOWN_EXT.test(f.path) ? (
                      <Markdown fontSize={11.5}>{entry.content || ''}</Markdown>
                    ) : (
                      <pre style={{ margin: 0, padding: '8px 10px', fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--ink2)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{entry.content}</pre>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function CommandLogPanel({ commands }: { commands: CommandEntry[] }) {
  return (
    <div>
      <PanelHeader>{commands.length} command{commands.length !== 1 ? 's' : ''} run</PanelHeader>
      {commands.length === 0 && <PanelEmptyState>Shell commands the agent runs will appear here, with the time each one ran.</PanelEmptyState>}
      {commands.map((c, i) => {
        const ts = new Date(c.timestamp)
        const tsStr = `${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}:${String(ts.getSeconds()).padStart(2, '0')}`
        return (
          <div key={i} style={{ display: 'flex', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--line)', fontSize: 11 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--mut2)', flexShrink: 0 }}>{tsStr}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink2)', wordBreak: 'break-all' }}>{c.command}</span>
          </div>
        )
      })}
    </div>
  )
}

/** A small in-panel browser — real tabs, like the one on your desktop.
 * Type/paste a URL like any address bar, or click a link the agent
 * posts in chat (see Markdown's onLinkClick) and it opens in a new tab
 * here instead of leaving the app. Each tab is just an <iframe>; a site
 * that sends X-Frame-Options/CSP frame-ancestors can still refuse to
 * render inside one, which is why "open in new tab" (the real browser's)
 * is always available as an escape hatch rather than something to try
 * to detect and work around.
 *
 * Only the active tab's iframe is ever mounted — switching tabs remounts
 * it fresh at that tab's URL rather than keeping every tab's iframe
 * alive in the background. For dev-server previews (the actual use
 * case) there's no meaningful client state worth preserving across a
 * switch, so this is a deliberate simplification over a real browser's
 * per-tab process model.
 */
function BrowserPanel({
  tabs, activeTabId, onSelectTab, onCloseTab, onNewTab, onUrlChange,
}: {
  tabs: BrowserTab[]
  activeTabId: string
  onSelectTab: (id: string) => void
  onCloseTab: (id: string) => void
  onNewTab: () => void
  onUrlChange: (tabId: string, url: string) => void
}) {
  const activeTab = tabs.find(t => t.id === activeTabId) ?? tabs[0]
  const [draft, setDraft] = useState(activeTab?.url ?? '')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => { setDraft(activeTab?.url ?? '') }, [activeTab?.id, activeTab?.url])

  const commit = (raw: string) => {
    const trimmed = raw.trim()
    if (!trimmed || !activeTab) return
    const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`
    onUrlChange(activeTab.id, withScheme)
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '4px 4px 0', borderBottom: '1px solid var(--line)', overflowX: 'auto' }}>
        {tabs.map(t => {
          const active = t.id === activeTabId
          return (
            <div
              key={t.id}
              onClick={() => onSelectTab(t.id)}
              title={t.url || 'New Tab'}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', borderRadius: '6px 6px 0 0',
                fontSize: 11, cursor: 'pointer', maxWidth: 140, flexShrink: 0,
                background: active ? 'var(--card2)' : 'transparent',
                color: active ? 'var(--ink)' : 'var(--mut)',
                borderBottom: active ? '2px solid var(--acc)' : '2px solid transparent',
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{browserTabLabel(t.url)}</span>
              <span
                onClick={e => { e.stopPropagation(); onCloseTab(t.id) }}
                title="Close tab"
                style={{ fontSize: 10, color: 'var(--mut)', flexShrink: 0, padding: '0 2px' }}
              >
                ✕
              </span>
            </div>
          )
        })}
        <button onClick={onNewTab} title="New tab" style={{ padding: '5px 9px', fontSize: 13, color: 'var(--mut)', flexShrink: 0 }}>+</button>
      </div>
      <div style={{ display: 'flex', gap: 6, padding: 6, borderBottom: '1px solid var(--line)' }}>
        <button
          onClick={() => setReloadKey(k => k + 1)}
          title="Reload"
          disabled={!activeTab?.url}
          style={{ padding: '4px 8px', borderRadius: 6, fontSize: 12, color: 'var(--ink2)', background: 'var(--card2)', opacity: activeTab?.url ? 1 : 0.4 }}
        >
          ⟳
        </button>
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(draft) }}
          placeholder="Enter a URL to preview…"
          style={{ flex: 1, minWidth: 0, padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line2)', background: 'var(--card2)', color: 'var(--ink)', fontSize: 11.5, fontFamily: 'var(--font-mono)', outline: 'none' }}
        />
        <button
          onClick={() => commit(draft)}
          style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}
        >
          Go
        </button>
        <a
          href={activeTab?.url || undefined}
          target="_blank"
          rel="noreferrer"
          title="Open in new browser tab"
          style={{ padding: '4px 8px', borderRadius: 6, fontSize: 12, color: 'var(--ink2)', background: 'var(--card2)', opacity: activeTab?.url ? 1 : 0.4, pointerEvents: activeTab?.url ? 'auto' : 'none' }}
        >
          ↗
        </a>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        {activeTab?.url ? (
          <iframe
            key={`${activeTab.id}-${activeTab.url}-${reloadKey}`}
            src={activeTab.url}
            title="Browser"
            style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, padding: 20, textAlign: 'center' }}>
            <div style={{ fontSize: 28, opacity: 0.3 }}>🌐</div>
            <div style={{ fontSize: 13, color: 'var(--ink2)' }}>Browser</div>
            <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>Enter a URL above, or click a link the agent posts in chat.</div>
          </div>
        )}
      </div>
    </div>
  )
}

function browserTabLabel(url: string): string {
  if (!url) return 'New Tab'
  try {
    const u = new URL(url)
    return u.hostname + (u.pathname !== '/' ? u.pathname : '')
  } catch {
    return url
  }
}

export default AgentThread
