import { useCallback, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  fetchTask, updateTask, deleteTask, toggleCriterion, createSession, fetchAgent,
  type TaskDetail as TDetail, type AgentInfo,
} from '../lib/api'
import { useWorkspaceScope } from '../lib/workspaceContext'
import { statusStyle } from '../lib/statusColors'
import { priorityColor } from '../lib/priorityColors'
import { Card, Chip, SectionLabel } from '../components/primitives'
import DeskLayout from '../components/DeskLayout'
import TaskDialog from '../components/TaskDialog'

const LIFECYCLE = ['draft', 'open', 'in_progress', 'review', 'done']
const REVIEW_GATE_LABELS: Record<string, string> = {
  auto: '🛡 auto-review on completion',
  manual: 'review: ask me',
  none: 'no review gate',
}

function rel(e: number) {
  const d = Date.now() - e * 1000; const m = Math.floor(d / 60000)
  if (m < 1) return 'just now'; if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
function ts(e: number) { return new Date(e * 1000).toLocaleString() }

function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { workspace } = useWorkspaceScope()
  const [task, setTask] = useState<TDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [showEdit, setShowEdit] = useState(false)
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [related, setRelated] = useState<TDetail[]>([])
  const [error, setError] = useState('')

  const load = useCallback(() => {
    if (!id) return
    fetchTask(id).then(t => {
      setTask(t)
      setLoading(false)
      if (t.assigned_to) fetchAgent(t.assigned_to).then(setAgent).catch(() => setAgent(null))
      else setAgent(null)
      if (t.dependencies.length > 0) {
        Promise.all(t.dependencies.map(d => fetchTask(d).catch(() => null)))
          .then(rs => setRelated(rs.filter((r): r is TDetail => r !== null)))
      } else {
        setRelated([])
      }
    }).catch(() => setLoading(false))
  }, [id])

  useEffect(() => { load() }, [load])

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

  if (loading) return <DeskLayout width={880}><Card>Loading…</Card></DeskLayout>
  if (!task) return <DeskLayout width={880}><Card>Task not found.</Card></DeskLayout>

  const stepsDone = task.steps.filter(s => s.status === 'done').length
  const metSet = new Set(task.criteria_met)

  const stageIndex = LIFECYCLE.indexOf(task.status === 'blocked' ? 'in_progress' : task.status === 'planned' ? 'open' : task.status)

  return (
    <DeskLayout width={880}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <button onClick={() => navigate('/tasks')} style={{ color: 'var(--ink2)', fontSize: 16 }}>←</button>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)' }}>{task.id}</span>
        <Chip color={statusStyle(task.status).color} soft>{statusStyle(task.status).label}</Chip>
        <Chip color={priorityColor(task.priority)} soft>{task.priority}</Chip>
        {task.project && <Chip mono>{task.project}</Chip>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {task.assigned_to ? (
            <button
              onClick={() => navigate(`/agent/${task.assigned_to}`)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--ok-soft)', color: 'var(--ok)' }}
            >
              ● Agent active — open thread →
            </button>
          ) : (
            <>
              <button
                onClick={() => handleStart(false)}
                disabled={task.unmet_dependencies.length > 0}
                title={task.unmet_dependencies.length > 0 ? 'Blocked by unfinished dependencies — see below' : 'Start and open the thread now'}
                style={{ padding: '5px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: task.unmet_dependencies.length > 0 ? 0.5 : 1, cursor: task.unmet_dependencies.length > 0 ? 'not-allowed' : 'pointer' }}
              >
                ▶ Start (watch)
              </button>
              <button
                onClick={() => handleStart(true)}
                disabled={task.unmet_dependencies.length > 0}
                title={task.unmet_dependencies.length > 0 ? 'Blocked by unfinished dependencies — see below' : 'Start in the background — open the thread later'}
                style={{ padding: '5px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)', opacity: task.unmet_dependencies.length > 0 ? 0.5 : 1, cursor: task.unmet_dependencies.length > 0 ? 'not-allowed' : 'pointer' }}
              >
                ⏵ Start headless
              </button>
            </>
          )}
          <button onClick={() => setShowEdit(true)} style={{ padding: '5px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Edit</button>
          <button onClick={handleDelete} style={{ padding: '5px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--err)', background: 'var(--card2)' }}>✕ Delete</button>
        </div>
      </div>

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
            <button onClick={handleRunReview} style={{ padding: '5px 12px', borderRadius: 8, fontSize: 12, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}>
              Run review now
            </button>
          </div>
        </Card>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 20 }}>
        <div>
          {/* Title + tags */}
          <div style={{ marginBottom: 20 }}>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--ink)', marginBottom: 8 }}>{task.title}</h1>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {task.tags.map(tag => <Chip key={tag}>{tag}</Chip>)}
            </div>
          </div>

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
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--mut)' }}>{rel(p.timestamp)}</span>
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
          {agent && (
            <SideBlock label="Session">
              <Row l="Mode" v={agent.mode} />
              <Row l="Tokens" v={agent.tokens_used.toLocaleString()} />
              <Row l="Cost" v={`$${agent.cost_usd.toFixed(3)}`} />
              <button
                onClick={() => navigate(`/agent/${agent.id}`)}
                style={{ marginTop: 6, fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}
              >
                Open thread →
              </button>
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
            <Row l="Created" v={ts(task.created_at)} />
            <Row l="Updated" v={rel(task.updated_at)} />
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

export default TaskDetail
