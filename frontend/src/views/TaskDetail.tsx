import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  fetchTask, updateTask, deleteTask, toggleCriterion, createSession, fetchTaskAgents, fetchTaskHistory, answerAgent,
  type TaskDetail as TDetail, type AgentInfo, type PastSession,
} from '../lib/api'
import { useWorkspaceScope } from '../lib/workspaceContext'
import { statusStyle } from '../lib/statusColors'
import { computeAgentState, AGENT_STATE_TOKENS } from '../lib/agentState'
import { timeAgo } from '../lib/format'
import { useClickOutside } from '../lib/useClickOutside'
import { Card, Chip, SectionLabel, Spinner } from '../components/primitives'
import DeskLayout from '../components/DeskLayout'
import TaskDialog from '../components/TaskDialog'

const LIFECYCLE = ['draft', 'open', 'in_progress', 'review', 'done']
const REVIEW_GATE_LABELS: Record<string, string> = {
  auto: '🛡 auto-review on completion',
  manual: 'review: ask me',
  none: 'no review gate',
}

function ts(e: number) { return new Date(e * 1000).toLocaleString() }

function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { workspace } = useWorkspaceScope()
  const [task, setTask] = useState<TDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [showEdit, setShowEdit] = useState(false)
  // The kebab menu in the header. useRef + useClickOutside mirrors the
  // pattern in NotificationBell/WorkspaceSwitcher so it closes on an
  // outside mousedown without each call site re-rolling the listener.
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  useClickOutside(menuRef, menuOpen, () => setMenuOpen(false))
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [pastSessions, setPastSessions] = useState<PastSession[]>([])
  const [related, setRelated] = useState<TDetail[]>([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    try {
      // Fetched together, not task-then-agents sequentially — otherwise
      // the page renders with task loaded but agents still empty for a
      // beat, showing the Start buttons before flipping to "Watch" once
      // the agents call catches up. Whether an agent is already on this
      // task needs to be known from the very first render, not a moment
      // after it.
      const [t, agentsRes, historyRes] = await Promise.all([
        fetchTask(id),
        fetchTaskAgents(id).catch(() => ({ agents: [] })),
        fetchTaskHistory(id).catch(() => ({ sessions: [] })),
      ])
      setTask(t)
      setAgents(agentsRes.agents)
      setPastSessions(historyRes.sessions)
      setLoading(false)
      if (t.dependencies.length > 0) {
        const rs = await Promise.all(t.dependencies.map(d => fetchTask(d).catch(() => null)))
        setRelated(rs.filter((r): r is TDetail => r !== null))
      } else {
        setRelated([])
      }
    } catch {
      setLoading(false)
    }
  }, [id])

  // Poll so progress/status an agent writes while this page is open
  // shows up without a manual reload — same 5s cadence as the
  // Board/List task views (useTaskList.ts), which this page had no
  // equivalent of at all before.
  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  const handleToggleCriterion = async (criterion: string, met: boolean) => {
    if (!id) return
    const updated = await toggleCriterion(id, criterion, met)
    setTask(updated)
  }

  const handleStart = async (headless: boolean) => {
    if (!id) return
    setError('')
    try {
      const session = await createSession({ prompt: '', mode: 'agent', task_id: id, project_id: workspace || undefined })
      if (headless) load() // refresh so the "Agent active" link appears
      else navigate(`/agent/${session.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start session')
    }
  }

  const handleRunReview = async () => {
    if (!id) return
    setError('')
    try {
      const updated = await updateTask(id, { status: 'done' })
      setTask(updated)
    } catch {
      setError('Not all acceptance criteria are met yet — done was refused.')
    }
  }

  const handleDelete = async () => {
    if (!id) return
    await deleteTask(id)
    navigate('/tasks')
  }

  if (loading) return <DeskLayout scale="narrow"><Card style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner /></Card></DeskLayout>
  if (!task) return <DeskLayout scale="narrow"><Card>Task not found.</Card></DeskLayout>

  const stepsDone = task.steps.filter(s => s.status === 'done').length
  const metSet = new Set(task.criteria_met)
  // task.assigned_to is never cleared when a session stops, so it can
  // point at a dead session — agents (fetched live via
  // fetchTaskAgents) is the accurate signal for whether someone's
  // actually still on this task right now.
  const activeWriter = agents.find(a => !a.advisory)
  // Three-state indicator on the watch card (green/amber/red), shared
  // with the Board's task card via lib/agentState so both surfaces agree.
  const agentState = activeWriter
    ? computeAgentState(true, activeWriter.running, activeWriter.error)
    : null
  const st = agentState ? AGENT_STATE_TOKENS[agentState] : null

  const stageIndex = LIFECYCLE.indexOf(task.status === 'blocked' ? 'in_progress' : task.status === 'planned' ? 'open' : task.status)

  return (
    <DeskLayout scale="narrow">
      {/* Header — title-led. The bar carries the task's identity (title +
          status/project chips); priority lives in the Metadata side block.
          The right-hand action zone is either a single primary Start (idle),
          or a green "watch card" when an agent is live — the thing you most
          want to do (jump to the thread) becomes the whole action zone.
          Rare + destructive actions (headless, edit, delete) sit behind a
          kebab so Delete is never a mis-click away from Start. */}
      <Card
        raised
        style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, padding: '10px 14px' }}
      >
        <button
          onClick={() => navigate('/tasks')}
          title="Back to tasks"
          style={{ color: 'var(--ink2)', fontSize: 17, width: 30, height: 30, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
        >←</button>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{task.title}</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <Chip color={statusStyle(task.status).color} soft>{statusStyle(task.status).label}</Chip>
            {task.project && <Chip mono>{task.project}</Chip>}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {activeWriter && st ? (
            <button
              onClick={() => navigate(`/agent/${activeWriter.id}`)}
              title={`Open ${activeWriter.name}'s thread · ${st.label}`}
              style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '4px 6px 4px 11px', borderRadius: 9, cursor: 'pointer', background: st.soft, border: `1px solid color-mix(in srgb, ${st.color} 35%, transparent)` }}
            >
              <span
                className={agentState === 'running' ? 'ak-pulse' : undefined}
                style={{ width: 8, height: 8, borderRadius: '50%', background: st.color, color: st.color, flexShrink: 0, position: 'relative' }}
              />
              <span style={{ fontSize: 12.5, fontWeight: 700, color: st.color }}>{activeWriter.name}</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--acc-ink)', background: st.color, padding: '3px 9px', borderRadius: 6, display: 'inline-flex', alignItems: 'center', gap: 4 }}>Watch →</span>
            </button>
          ) : (
            <button
              onClick={() => handleStart(false)}
              disabled={task.unmet_dependencies.length > 0}
              title={task.unmet_dependencies.length > 0 ? 'Blocked by unfinished dependencies — see below' : 'Start and open the thread now'}
              style={{ padding: '6px 13px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: task.unmet_dependencies.length > 0 ? 0.5 : 1, cursor: task.unmet_dependencies.length > 0 ? 'not-allowed' : 'pointer' }}
            >
              ▶ Start
            </button>
          )}
          <div ref={menuRef} style={{ position: 'relative' }}>
            <button
              onClick={() => setMenuOpen(o => !o)}
              title="More"
              style={{ width: 32, height: 30, borderRadius: 8, background: 'var(--card2)', color: 'var(--ink2)', fontSize: 16, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
            >⋯</button>
            {menuOpen && (
              <div style={{ position: 'absolute', right: 0, top: 36, minWidth: 172, zIndex: 200, background: 'var(--card)', border: '1px solid var(--line2)', borderRadius: 10, boxShadow: 'var(--shadow)', padding: 5 }}>
                {/* Headless start only makes sense when there's no active
                    writer (you can't start a second writer on the same
                    task) and the task isn't blocked. */}
                {!activeWriter && (
                  <button
                    onClick={() => { setMenuOpen(false); handleStart(true) }}
                    disabled={task.unmet_dependencies.length > 0}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '7px 10px', border: 'none', background: 'transparent', cursor: task.unmet_dependencies.length > 0 ? 'not-allowed' : 'pointer', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 500, color: 'var(--ink2)', borderRadius: 7, textAlign: 'left', opacity: task.unmet_dependencies.length > 0 ? 0.5 : 1 }}
                  >⏵ Start headless</button>
                )}
                <button
                  onClick={() => { setMenuOpen(false); setShowEdit(true) }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '7px 10px', border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 500, color: 'var(--ink2)', borderRadius: 7, textAlign: 'left' }}
                >✎ Edit task</button>
                <div style={{ height: 1, background: 'var(--line)', margin: '4px 6px' }} />
                <button
                  onClick={() => { setMenuOpen(false); handleDelete() }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '7px 10px', border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 500, color: 'var(--err)', borderRadius: 7, textAlign: 'left' }}
                >✕ Delete task</button>
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* Agent pending question — answerable from here, no need to open the thread.
          Any agent on the task can block, not just the writer, so this scans all of them. */}
      {agents.filter(a => a.pending_question).map(a => (
        <PendingQuestionCard key={a.id} agentId={a.id} pq={a.pending_question!} onAnswered={load} />
      ))}

      {/* Lifecycle strip */}
      <Card style={{ marginBottom: 20, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          {LIFECYCLE.map((stage, i) => {
            const past = i < stageIndex
            const current = i === stageIndex
            const color = current
              ? (task.status === 'blocked' ? 'var(--warn)' : 'var(--acc)')
              : past ? 'var(--ok)' : 'var(--mut2)'
            return (
              <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: color }} />
                  <span style={{ fontSize: 11.5, fontWeight: current ? 700 : 500, color }}>{stage.replace('_', ' ')}</span>
                </div>
                {i < LIFECYCLE.length - 1 && <span style={{ color: 'var(--line2)', margin: '0 4px' }}>→</span>}
              </div>
            )
          })}
          {(task.status === 'blocked' || task.status === 'planned' || task.status === 'abandoned') && (
            <span style={{ fontSize: 11, color: 'var(--mut)', marginLeft: 8 }}>({task.status})</span>
          )}
        </div>
        <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>{REVIEW_GATE_LABELS[task.review_gate] || task.review_gate}</span>
      </Card>

      {task.unmet_dependencies.length > 0 && (
        <Card style={{ marginBottom: 20, background: 'var(--warn-soft)', border: '1px solid var(--warn)' }}>
          <span style={{ fontSize: 13, color: 'var(--ink)' }}>
            🔗 Blocked by: {task.unmet_dependencies.map((d, i) => (
              <span key={d.id}>
                {i > 0 && ', '}
                <a onClick={() => navigate(`/tasks/${d.id}`)} style={{ color: 'var(--warn-ink)', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline' }}>{d.title}</a>
              </span>
            ))} — this task can't be started until {task.unmet_dependencies.length > 1 ? 'these are' : 'it is'} done.
          </span>
        </Card>
      )}

      {error && <div style={{ fontSize: 12.5, color: 'var(--err)', marginBottom: 14 }}>{error}</div>}

      {task.status === 'review' && task.review_gate === 'auto' && (
        <Card style={{ marginBottom: 20, background: 'var(--acc-soft)', border: '1px solid var(--acc)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 13, color: 'var(--ink)' }}>🛡 Auto-review queued — all criteria must be met before this can complete.</span>
            <button onClick={handleRunReview} style={{ padding: '5px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}>
              Run review now
            </button>
          </div>
        </Card>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 20 }}>
        <div>
          {/* Tags — title now lives in the header bar, so this is just the
              tag row. Kept as its own block so an empty tags list doesn't
              leave a gap (marginBottom only applied when there are tags). */}
          {task.tags.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
              {task.tags.map(tag => <Chip key={tag}>{tag}</Chip>)}
            </div>
          )}

          {task.description && (
            <Section label="Description">
              <Card style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--ink2)' }}>{task.description}</Card>
            </Section>
          )}

          {task.steps.length > 0 && (
            <Section label={`Steps · ${stepsDone}/${task.steps.length} done`}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {task.steps.map(s => {
                  const done = s.status === 'done'; const active = s.status === 'in_progress'
                  return (
                    <div key={s.id} style={{ fontSize: 13, color: done ? 'var(--mut)' : 'var(--ink2)', textDecoration: done ? 'line-through' : undefined, display: 'flex', gap: 8 }}>
                      <span>{done ? '✓' : active ? '●' : '○'}</span>
                      <span>{s.title}</span>
                      {s.sub_steps.length > 0 && (
                        <ul style={{ marginLeft: 20, marginTop: 4 }}>
                          {s.sub_steps.map(ss => <li key={ss.id} style={{ fontSize: 12, color: 'var(--mut)' }}>{ss.title}</li>)}
                        </ul>
                      )}
                    </div>
                  )
                })}
              </div>
            </Section>
          )}

          {task.acceptance_criteria.length > 0 && (
            <Section label="Acceptance criteria">
              <div style={{ fontSize: 11.5, color: 'var(--mut)', marginBottom: 8 }}>Done is gated on all criteria being marked met.</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {task.acceptance_criteria.map((c, i) => {
                  const met = metSet.has(c)
                  return (
                    <label
                      key={i}
                      onClick={() => handleToggleCriterion(c, !met)}
                      style={{
                        display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, cursor: 'pointer',
                        padding: '6px 8px', borderRadius: 6, background: met ? 'var(--acc-soft)' : undefined,
                      }}
                    >
                      <span style={{
                        width: 15, height: 15, borderRadius: 4, flexShrink: 0, marginTop: 1,
                        border: `1px solid ${met ? 'var(--acc)' : 'var(--line2)'}`,
                        background: met ? 'var(--acc)' : 'transparent',
                        color: 'var(--acc-ink)', fontSize: 11, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>{met ? '✓' : ''}</span>
                      <span style={{ color: met ? 'var(--ink)' : 'var(--ink2)' }}>{c}</span>
                    </label>
                  )
                })}
              </div>
            </Section>
          )}

          {task.progress.length > 0 && (
            <Section label="Progress log">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {[...task.progress].reverse().map((p, i) => {
                  const blocked = p.status === 'blocked' || !!p.blocker
                  return (
                    <Card key={i} style={blocked ? { border: '1px solid var(--warn)' } : {}}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: blocked ? 'var(--warn-ink)' : 'var(--mut)' }}>{p.status.replace('_', ' ')}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--mut)' }}>{timeAgo(p.timestamp)}</span>
                      </div>
                      <div style={{ fontSize: 13, color: 'var(--ink2)', lineHeight: 1.5 }}>{p.entry}</div>
                      {p.blocker?.question && (
                        <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 6, background: 'var(--warn-soft)', fontStyle: 'italic', fontSize: 13, color: 'var(--ink)' }}>
                          {p.blocker.question}
                        </div>
                      )}
                      {p.next_step && <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 6 }}>Next: {p.next_step}</div>}
                    </Card>
                  )
                })}
              </div>
            </Section>
          )}
        </div>

        {/* Side blocks */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* One block per active session on this task — the writer plus
              any read-only advisory agents (e.g. a reviewer role) sharing
              its working tree. Writer sorts first. */}
          {[...agents].sort((a, b) => Number(a.advisory) - Number(b.advisory)).map(a => (
            <SideBlock key={a.id} label={a.advisory ? `🛡 ${a.name} · ${a.role || 'agent'}` : a.name}>
              <Row l="Mode" v={a.mode} />
              {a.branch && <Row l="Branch" v={a.branch} mono />}
              <Row l="Tokens" v={a.tokens_used.toLocaleString()} />
              <Row l="Cost" v={`$${a.cost_usd.toFixed(3)}`} />
              <button
                onClick={() => navigate(`/agent/${a.id}`)}
                style={{ marginTop: 6, fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}
              >
                Open thread →
              </button>
            </SideBlock>
          ))}
          {/* Finished sessions — stopped, but their full transcript
              survives in the wastebin and can still be reopened
              read-only via /agent/{id} (routes/agents.py falls back to
              it once the session's no longer live). */}
          {pastSessions.length > 0 && (
            <SideBlock label="Past sessions">
              {pastSessions.map(s => (
                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
                  <span style={{ fontSize: 11.5, color: 'var(--ink2)', flex: 1 }}>
                    {s.advisory ? `🛡 ${s.role || 'advisory'}` : 'writer'} · {timeAgo(s.stopped_at)}
                  </span>
                  <button
                    onClick={() => navigate(`/agent/${s.id}`)}
                    style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}
                  >
                    Watch {s.name} →
                  </button>
                </div>
              ))}
            </SideBlock>
          )}
          <SideBlock label="Tools used">
            {toolCounts(task.progress).length === 0 && <span style={{ fontSize: 12, color: 'var(--mut)' }}>None yet</span>}
            {toolCounts(task.progress).map(([name, count]) => (
              <Row key={name} l={name} v={`×${count}`} mono />
            ))}
          </SideBlock>
          {related.length > 0 && (
            <SideBlock label="Depends on">
              {related.map(r => (
                <div key={r.id} onClick={() => navigate(`/tasks/${r.id}`)} style={{ fontSize: 12, color: statusStyle(r.status).color, cursor: 'pointer', marginBottom: 4 }}>
                  {r.status === 'done' ? '✓' : '○'} {r.title}
                </div>
              ))}
            </SideBlock>
          )}
          {task.required_credentials.length > 0 && (
            <SideBlock label="Vault credentials">
              {task.required_credentials.map(c => <Row key={c} l="⚿" v={c} mono />)}
            </SideBlock>
          )}
          <SideBlock label="Metadata">
            {/* Priority lives here rather than as a chip in the header —
                the header carries status + project (identity), while
                priority is a property you check occasionally, not glance
                at. Colored to match the priority's accent so it still
                reads at a glance. */}
            <Row l="Priority" v={task.priority} />
            <Row l="Created" v={ts(task.created_at)} />
            <Row l="Updated" v={timeAgo(task.updated_at)} />
          </SideBlock>
        </div>
      </div>

      <TaskDialog
        open={showEdit}
        task={task}
        onClose={() => setShowEdit(false)}
        onSaved={() => { setShowEdit(false); load() }}
      />
    </DeskLayout>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return <div style={{ marginBottom: 22 }}><div style={{ marginBottom: 10 }}><SectionLabel>{label}</SectionLabel></div>{children}</div>
}

function SideBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return <Card><div style={{ marginBottom: 10 }}><SectionLabel>{label}</SectionLabel></div>{children}</Card>
}

function Row({ l, v, mono }: { l: string; v: string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}>
      <span style={{ color: 'var(--mut)', fontFamily: mono ? 'var(--font-mono)' : undefined }}>{l}</span>
      <span style={{ color: 'var(--ink2)', fontFamily: mono ? 'var(--font-mono)' : undefined }}>{v}</span>
    </div>
  )
}

function toolCounts(progress: TDetail['progress']): [string, number][] {
  const counts = new Map<string, number>()
  for (const p of progress) {
    const m = p.entry.match(/^\[([^\]]+)\]/)
    if (m) counts.set(m[1], (counts.get(m[1]) || 0) + 1)
  }
  return [...counts.entries()]
}

function PendingQuestionCard({ agentId, pq, onAnswered }: { agentId: string; pq: { question: string; options: string[] | null }; onAnswered: () => void }) {
  const [answer, setAnswer] = useState('')
  const [sending, setSending] = useState(false)

  const handleAnswer = async (text: string) => {
    if (!text.trim() || sending) return
    setSending(true)
    try {
      await answerAgent(agentId, text.trim())
      setAnswer('')
      onAnswered()
    } catch { setSending(false) }
  }

  return (
    <Card style={{ marginBottom: 20, border: '2px solid var(--acc)', borderLeft: '4px solid var(--acc)' }}>
      <div style={{ fontSize: 12.5, color: 'var(--ink)', fontStyle: 'italic', marginBottom: 8, lineHeight: 1.5 }}>
        ❓ {pq.question}
      </div>
      {pq.options && pq.options.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
          {pq.options.map((o, i) => (
            <button key={i} disabled={sending} onClick={() => handleAnswer(o)}
              style={{ fontSize: 12.5, padding: '5px 12px', borderRadius: 8, background: 'var(--acc-soft)', color: 'var(--acc)', fontWeight: 600, opacity: sending ? 0.6 : 1 }}
            >{o}</button>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={answer}
          onChange={e => setAnswer(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleAnswer(answer) }}
          placeholder="Answer…"
          disabled={sending}
          style={{ flex: 1, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--line2)', background: 'var(--card2)', color: 'var(--ink)', fontSize: 12.5, outline: 'none', fontFamily: 'inherit', opacity: sending ? 0.6 : 1 }}
        />
        {/* Same padding as every other primary-action button in this
            file (header Edit/Delete/Start/Watch, Run review now) — was
            6px 16px here, an unexplained one-off. */}
        <button onClick={() => handleAnswer(answer)} disabled={sending || !answer.trim()}
          style={{ padding: '5px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', whiteSpace: 'nowrap', opacity: sending || !answer.trim() ? 0.6 : 1 }}
        >Answer</button>
      </div>
    </Card>
  )
}

export default TaskDetail
