import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchTask, updateTask, deleteTask, type TaskDetail as TDetail } from '../lib/api'

const STATUSES = ['draft', 'open', 'planned', 'in_progress', 'blocked', 'review', 'done', 'abandoned']
const PRIORITIES = ['low', 'medium', 'high', 'urgent']
const STATUS_COLORS: Record<string, string> = {
  draft: 'var(--muted-2)', open: 'var(--fg-soft)', planned: 'var(--info)',
  in_progress: 'oklch(72% 0.16 155)', blocked: 'var(--blocked)', review: 'oklch(70% 0.14 295)',
  done: 'var(--done)', abandoned: 'var(--muted-2)',
}

function ts(e: number) { return new Date(e * 1000).toLocaleString() }
function rel(e: number) {
  const d = Date.now() - e * 1000; const m = Math.floor(d / 60000)
  if (m < 1) return 'just now'; if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<TDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [eTitle, setETitle] = useState(''); const [eDesc, setEDesc] = useState('')
  const [ePriority, setEPriority] = useState('medium'); const [eStatus, setEStatus] = useState('open')
  const [eTags, setETags] = useState(''); const [eCriteria, setECriteria] = useState('')
  const [saving, setSaving] = useState(false)

  const load = () => { if (!id) return; fetchTask(id).then(t => {
    setTask(t); setETitle(t.title); setEDesc(t.description); setEPriority(t.priority)
    setEStatus(t.status); setETags(t.tags.join(', ')); setECriteria(t.acceptance_criteria.join('\n'))
    setLoading(false)
  }).catch(() => setLoading(false)) }
  useEffect(() => { load() }, [id])

  const handleStatusChange = async (s: string) => { if (!id) return; await updateTask(id, { status: s }); setTask(t => t ? { ...t, status: s } : t) }
  const handleSave = async () => { if (!id) return; setSaving(true)
    await updateTask(id, { title: eTitle, description: eDesc, priority: ePriority })
    if (eStatus !== task?.status) await updateTask(id, { status: eStatus })
    setShowModal(false); setSaving(false); load() }
  const handleDelete = async () => { if (!id) return; await deleteTask(id); navigate(-1) }

  if (loading) return <div style={center}>Loading...</div>
  if (!task) return <div style={center}>Task not found.</div>
  const stepsDone = task.steps.filter(s => s.status === 'done').length

  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <div style={{ padding: '12px 20px', display: 'flex', gap: 8, fontSize: 12, color: 'var(--muted)', alignItems: 'center', borderBottom: '1px solid var(--border-subtle)' }}>
        <a href="#/board" style={{ color: 'var(--info)', textDecoration: 'none' }}>Tasks</a><span style={{ color: 'var(--muted-2)' }}>/</span>
        {task.project && <><a href="#/board" style={{ color: 'var(--info)', textDecoration: 'none' }}>{task.project}</a><span style={{ color: 'var(--muted-2)' }}>/</span></>}
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg-soft)' }}>{task.id}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={() => setShowModal(true)} className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }}>Edit task</button>
          <button onClick={handleDelete} className="btn btn-ghost" style={{ color: 'var(--blocked)', fontSize: 12, padding: '4px 10px' }}>Delete</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', minHeight: 0 }}>
        <div style={{ padding: '24px 32px 60px' }}>
          <div style={{ marginBottom: 28 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--muted-2)', fontSize: 13 }}>{task.id}</span>
              <select value={task.status} onChange={e => handleStatusChange(e.target.value)} style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 500,
                background: STATUS_COLORS[task.status]?.replace(')', ' / 0.12)'), color: STATUS_COLORS[task.status],
                border: `1px solid ${STATUS_COLORS[task.status]?.replace(')', ' / 0.25)')}`, cursor: 'pointer', outline: 'none', fontFamily: 'inherit' }}>
                {STATUSES.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>
              {task.tags.map(tag => <span key={tag} style={tagChip}>{tag}</span>)}
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, color: task.priority === 'urgent' ? 'oklch(72% 0.18 25)' : task.priority === 'high' ? 'oklch(78% 0.14 65)' : 'var(--muted)' }}>{task.priority.toUpperCase()}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h1 style={{ fontSize: 26, fontWeight: 600, letterSpacing: '-0.015em', color: 'var(--fg)', lineHeight: 1.25 }}>{task.title}</h1>
              <button onClick={() => setShowModal(true)} style={{ opacity: 0.35, color: 'var(--muted)', fontSize: 14, cursor: 'pointer', border: 0, background: 'none' }}
                onMouseEnter={e => e.currentTarget.style.opacity = '0.95'} onMouseLeave={e => e.currentTarget.style.opacity = '0.35'}>✎</button>
            </div>
            <div style={{ display: 'flex', gap: 14, marginTop: 14, fontSize: 13, color: 'var(--muted)' }}>
              {task.assigned_to && <><span style={{ color: 'var(--fg-soft)' }}>{task.assigned_to}</span><span style={{ color: 'var(--muted-2)' }}>·</span></>}
              <span>Created {rel(task.created_at)}</span><span style={{ color: 'var(--muted-2)' }}>·</span><span>Updated {rel(task.updated_at)}</span>
            </div>
          </div>

          {task.description && <Sec label="Description"><div style={{ background: 'var(--surface)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '16px 18px', fontSize: 14, lineHeight: 1.65, color: 'var(--fg-soft)' }}>{task.description}</div></Sec>}

          {task.steps.length > 0 && <Sec label={`Steps · ${stepsDone} of ${task.steps.length} done`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {task.steps.map(s => {
                const done = s.status === 'done'; const active = s.status === 'in_progress'
                return <div key={s.id} style={{
                  display: 'flex', gap: 14, padding: '14px 16px', borderRadius: 10,
                  border: done ? '1px solid oklch(64% 0.06 155 / 0.2)' : active ? '1px solid oklch(68% 0.12 235 / 0.4)' : '1px solid var(--border-subtle)',
                  background: done ? 'oklch(64% 0.06 155 / 0.04)' : active ? 'oklch(68% 0.12 235 / 0.06)' : 'var(--surface)',
                  opacity: (!done && !active) ? 0.55 : 1,
                }}>
                  <div style={{ width: 28, height: 28, borderRadius: '50%', display: 'grid', placeItems: 'center', flexShrink: 0, fontSize: 12, fontWeight: 600,
                    background: done ? 'oklch(64% 0.06 155 / 0.15)' : active ? 'oklch(68% 0.12 235 / 0.15)' : 'var(--surface-raised)',
                    border: `1px solid ${done ? 'oklch(64% 0.06 155 / 0.3)' : active ? 'oklch(68% 0.12 235 / 0.3)' : 'var(--border-subtle)'}`,
                    color: done ? 'oklch(64% 0.06 155)' : active ? 'var(--info)' : 'var(--muted)' }}>{done ? '✓' : (s.id.replace('s-', '') || '·')}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                      <span style={{ fontSize: 14, fontWeight: 500, color: done ? 'var(--fg-soft)' : active ? 'var(--fg)' : 'var(--muted)', textDecoration: done ? 'line-through' : 'none' }}>{s.title}</span>
                      {done && <span style={markDone}>Done</span>}{active && <span style={markActive}>Active</span>}
                    </div>
                    {s.notes && <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.5 }}>{s.notes}</div>}
                  </div>
                </div>
              })}
            </div>
          </Sec>}

          {task.acceptance_criteria.length > 0 && <Sec label="Acceptance Criteria">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {task.acceptance_criteria.map((c, i) => (
                <label key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13, lineHeight: 1.4, color: 'var(--fg-soft)' }}>
                  <input type="checkbox" style={{ margin: '2px 0 0 0', accentColor: 'var(--info)' }} /><span>{c}</span>
                </label>
              ))}
            </div>
          </Sec>}

          {task.progress.length > 0 && <Sec label="Progress log">
            <div style={{ position: 'relative', paddingLeft: 32 }}>
              <div style={{ position: 'absolute', left: 11, top: 0, bottom: 0, width: 1, background: 'var(--border)' }} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {[...task.progress].reverse().map((p, i) => {
                  const blk = p.status === 'blocked' || p.blocker
                  const mc = blk ? 'var(--blocked)' : p.status === 'done' ? 'var(--done)' : 'var(--info)'
                  return <div key={i} style={{ position: 'relative' }}>
                    <div style={{ position: 'absolute', left: -25, top: 14, width: 11, height: 11, borderRadius: '50%', background: mc, border: '2px solid var(--bg)' }} />
                    <div style={{ background: blk ? 'var(--blocked-bg)' : 'var(--surface)', border: `1px solid ${blk ? 'var(--blocked-bd)' : 'var(--border-subtle)'}`, borderRadius: 10, padding: '12px 14px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                        <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: mc }}>{p.status.replace('_', ' ')}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted-2)' }}>{rel(p.timestamp)}</span>
                      </div>
                      <div style={{ fontSize: 13, lineHeight: 1.55, color: blk ? 'var(--fg)' : 'var(--fg-soft)' }}>{p.entry}</div>
                      {p.blocker?.question && <div style={{ background: 'var(--blocked-bg)', borderRadius: 6, padding: '8px 10px', marginTop: 8, fontStyle: 'italic', color: 'var(--fg)', fontSize: 13 }}>{p.blocker.question}</div>}
                      {p.next_step && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>Next: {p.next_step}</div>}
                    </div>
                  </div>
                })}
              </div>
            </div>
          </Sec>}
        </div>

        <div style={{ background: 'var(--surface)', borderLeft: '1px solid var(--border)', padding: 16, overflowY: 'auto' }}>
          <Side label="Progress">
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}><span style={{ color: 'var(--muted)' }}>Overall</span><span style={{ fontFamily: 'var(--font-mono)', color: 'var(--info)' }}>{task.steps.length > 0 ? Math.round((stepsDone / task.steps.length) * 100) : 0}%</span></div>
            <div style={{ height: 4, background: 'var(--border)', borderRadius: 99, overflow: 'hidden', marginBottom: 12 }}><div style={{ height: '100%', width: `${task.steps.length > 0 ? Math.round((stepsDone / task.steps.length) * 100) : 0}%`, background: 'var(--info)' }} /></div>
            <Grid done={stepsDone} active={task.steps.filter(s => s.status === 'in_progress').length} pending={task.steps.filter(s => !['done', 'in_progress'].includes(s.status)).length} />
          </Side>
          <Side label="Metadata">
            <Row l="Workspace" v={task.project || '—'} /><Row l="Priority" v={task.priority} /><Row l="Assigned to" v={task.assigned_to || '—'} m />
            <Row l="Created" v={ts(task.created_at)} m /><Row l="Updated" v={rel(task.updated_at)} m />
          </Side>
        </div>
      </div>

      {showModal && <div style={mo} onClick={() => setShowModal(false)}>
        <div style={mb} onClick={e => e.stopPropagation()}>
          <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div><div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 4 }}>Editing task</div><div style={{ fontSize: 17, fontWeight: 600, color: 'var(--fg)' }}>{task.title}</div></div>
            <button onClick={() => setShowModal(false)} style={{ width: 28, height: 28, borderRadius: 6, color: 'var(--muted)', display: 'grid', placeItems: 'center', fontSize: 18, border: 0, background: 'none', cursor: 'pointer' }}>×</button>
          </div>
          <div style={{ padding: '18px 24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14, flex: 1 }}>
            <Fld l="Title"><input value={eTitle} onChange={e => setETitle(e.target.value)} style={mi} /></Fld>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
              <Fld l="Status"><select value={eStatus} onChange={e => setEStatus(e.target.value)} style={mi}>{STATUSES.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select></Fld>
              <Fld l="Priority"><select value={ePriority} onChange={e => setEPriority(e.target.value)} style={mi}>{PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}</select></Fld>
              <Fld l="Tags"><input value={eTags} onChange={e => setETags(e.target.value)} placeholder="comma, separated" style={mi} /></Fld>
            </div>
            <Fld l="Description"><textarea value={eDesc} onChange={e => setEDesc(e.target.value)} rows={4} style={{ ...mi, resize: 'vertical', minHeight: 80, lineHeight: 1.55, fontFamily: 'inherit' }} /></Fld>
            <Fld l="Acceptance criteria"><textarea value={eCriteria} onChange={e => setECriteria(e.target.value)} rows={3} style={{ ...mi, resize: 'vertical', minHeight: 60, fontFamily: 'inherit' }} placeholder="One per line" /></Fld>
          </div>
          <div style={{ padding: '14px 24px', borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--muted-2)', fontFamily: 'var(--font-mono)' }}>Esc to cancel</span>
            <div style={{ display: 'flex', gap: 8 }}><button onClick={() => setShowModal(false)} className="btn btn-ghost">Cancel</button>
              <button onClick={handleSave} disabled={saving} className="btn" style={{ background: 'var(--fg)', color: 'var(--bg)', fontWeight: 600 }}>{saving ? 'Saving...' : 'Save changes'}</button></div>
          </div>
        </div>
      </div>}
    </div>
  )
}

const center: React.CSSProperties = { padding: 40, color: 'var(--muted)' }
const mo: React.CSSProperties = { position: 'fixed', inset: 0, background: 'oklch(7% 0.004 260 / 0.65)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }
const mb: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, maxWidth: 720, width: '100%', maxHeight: '90vh', display: 'flex', flexDirection: 'column', boxShadow: '0 16px 48px rgba(0,0,0,0.45)' }
const mi: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--fg)', fontFamily: 'inherit', fontSize: 13, padding: '8px 10px', outline: 'none' }
const tagChip: React.CSSProperties = { fontSize: 11, padding: '2px 8px', borderRadius: 4, background: 'oklch(22% 0.008 260)', color: 'oklch(72% 0.008 260)' }
const markDone: React.CSSProperties = { fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', padding: '2px 6px', borderRadius: 3, color: 'oklch(64% 0.06 155)', background: 'oklch(64% 0.06 155 / 0.12)' }
const markActive: React.CSSProperties = { fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', padding: '2px 6px', borderRadius: 3, color: 'var(--info)', background: 'oklch(68% 0.12 235 / 0.15)' }

function Sec({ label, children }: { label: string; children: React.ReactNode }) { return <section style={{ marginBottom: 28 }}><div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 10 }}>{label}</div>{children}</section> }
function Side({ label, children }: { label: string; children: React.ReactNode }) { return <div style={{ background: 'var(--surface)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: 14, marginBottom: 12 }}><div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 10 }}>{label}</div>{children}</div> }
function Grid({ done, active, pending }: { done: number; active: number; pending: number }) { const c: React.CSSProperties = { background: 'var(--bg)', borderRadius: 6, padding: '8px 4px', textAlign: 'center' }; const n: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 500, fontVariantNumeric: 'tabular-nums' }; const l: React.CSSProperties = { fontSize: 10, color: 'var(--muted)', letterSpacing: '0.04em', textTransform: 'uppercase' }; return <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}><div style={c}><div style={{ ...n, color: 'var(--done)' }}>{done}</div><div style={l}>Done</div></div><div style={c}><div style={{ ...n, color: 'var(--info)' }}>{active}</div><div style={l}>Active</div></div><div style={c}><div style={{ ...n, color: 'var(--muted-2)' }}>{pending}</div><div style={l}>Pending</div></div></div> }
function Row({ l: label, v: value, m: mono }: { l: string; v: string; m?: boolean }) { return <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 7 }}><span style={{ color: 'var(--muted)' }}>{label}</span><span style={{ color: 'var(--fg-soft)', fontFamily: mono ? 'var(--font-mono)' : undefined, fontSize: mono ? '11.5px' : undefined }}>{value}</span></div> }
function Fld({ l: label, children }: { l: string; children: React.ReactNode }) { return <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}><label style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)' }}>{label}</label>{children}</div> }
