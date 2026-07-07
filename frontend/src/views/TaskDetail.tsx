import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchTask, updateTask, deleteTask, type TaskDetail as TDetail } from '../lib/api'

const STATUSES = ['draft', 'open', 'planned', 'in_progress', 'blocked', 'review', 'done', 'abandoned']
const PRIORITIES = ['low', 'medium', 'high', 'urgent']

function ts(epoch: number) { return new Date(epoch * 1000).toLocaleString() }

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<TDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editPriority, setEditPriority] = useState('medium')
  const [editTags, setEditTags] = useState('')
  const [editCriteria, setEditCriteria] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!id) return
    fetchTask(id).then(t => {
      setTask(t)
      setEditTitle(t.title)
      setEditDesc(t.description)
      setEditPriority(t.priority)
      setEditTags(t.tags.join(', '))
      setEditCriteria(t.acceptance_criteria.join('\n'))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [id])

  const handleStatusChange = async (status: string) => {
    if (!id || !task) return
    await updateTask(id, { status })
    setTask({ ...task, status })
  }

  const handlePriorityChange = async (priority: string) => {
    if (!id || !task) return
    await updateTask(id, { priority })
    setTask({ ...task, priority })
  }

  const handleSaveEdit = async () => {
    if (!id || !task) return
    setSaving(true)
    const tags = editTags.split(',').map(t => t.trim()).filter(Boolean)
    const criteria = editCriteria.split('\n').map(c => c.trim()).filter(Boolean)
    await updateTask(id, {
      title: editTitle,
      description: editDesc,
      priority: editPriority,
    })
    setTask({ ...task, title: editTitle, description: editDesc, priority: editPriority, tags, acceptance_criteria: criteria })
    setEditing(false)
    setSaving(false)
  }

  const handleDelete = async () => {
    if (!id) return
    await deleteTask(id)
    navigate(-1)
  }

  if (loading) return <div style={{ padding: 40, color: 'var(--muted)' }}>Loading...</div>
  if (!task) return <div style={{ padding: 40, color: 'var(--muted)' }}>Task not found.</div>

  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      {/* Breadcrumb */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--border-subtle)', fontSize: 13, color: 'var(--muted)' }}>
        <a href="#/board" style={{ color: 'var(--info)', textDecoration: 'none' }}>← Board</a>
        <span style={{ margin: '0 8px' }}>/</span>
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg-soft)' }}>{task.id}</span>
      </div>

      {/* Hero */}
      <div style={{ padding: '20px 20px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={editTitle} onChange={e => setEditTitle(e.target.value)} style={inp} autoFocus placeholder="Title" />
              <button onClick={handleSaveEdit} disabled={saving} className="btn"
                style={{ background: 'var(--info)', color: 'var(--bg)', fontWeight: 600 }}>Save</button>
              <button onClick={() => setEditing(false)} className="btn btn-ghost">Cancel</button>
            </div>
            <textarea value={editDesc} onChange={e => setEditDesc(e.target.value)} rows={2}
              style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }} placeholder="Description" />
            <div style={{ display: 'flex', gap: 8 }}>
              <select value={editPriority} onChange={e => setEditPriority(e.target.value)} style={{ ...sel, flex: 1 }}>
                {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <input value={editTags} onChange={e => setEditTags(e.target.value)}
              style={inp} placeholder="Tags (comma-separated)" />
            <textarea value={editCriteria} onChange={e => setEditCriteria(e.target.value)} rows={3}
              style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }} placeholder="Acceptance criteria (one per line)" />
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <h2 style={{ fontSize: 22, fontWeight: 700 }}>{task.title}</h2>
              <button onClick={() => setEditing(true)}
                style={{ color: 'var(--muted)', fontSize: 14, cursor: 'pointer', border: 0, background: 'none' }} title="Edit">✎</button>
            </div>
            <div style={{ display: 'flex', gap: 16, fontSize: 13, color: 'var(--fg-soft)', alignItems: 'center', flexWrap: 'wrap' }}>
              <select value={task.status} onChange={e => handleStatusChange(e.target.value)} style={{ ...sel, color: 'var(--fg)' }}>
                {STATUSES.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>
              <span style={{ color: 'var(--muted)' }}>·</span>
              <select value={task.priority} onChange={e => handlePriorityChange(e.target.value)} style={{ ...sel, color: 'var(--fg)' }}>
                {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
              {task.tags.map(tag => (
                <span key={tag} style={tagChip}>{tag}</span>
              ))}
              <span style={{ color: 'var(--muted)' }}>·</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{task.id}</span>
              <span style={{ marginLeft: 'auto' }}>
                <button onClick={handleDelete} className="btn btn-ghost" style={{ color: 'var(--blocked)', fontSize: 12 }}>Delete</button>
              </span>
            </div>
          </>
        )}
      </div>

      {/* Body */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 0, minHeight: 0 }}>
        <div style={{ padding: 20 }}>
          {task.description && (
            <div style={{ marginBottom: 24 }}>
              <div style={secHead}>Description</div>
              <p style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--fg-soft)' }}>{task.description}</p>
            </div>
          )}
          {task.acceptance_criteria.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={secHead}>Acceptance Criteria</div>
              {task.acceptance_criteria.map((c, i) => (
                <div key={i} style={{ fontSize: 13, color: 'var(--fg-soft)', padding: '4px 0', display: 'flex', gap: 8 }}>
                  <span style={{ color: 'var(--muted)' }}>☐</span> {c}
                </div>
              ))}
            </div>
          )}
          {task.steps.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={secHead}>Steps</div>
              {task.steps.map(s => (
                <div key={s.id} style={{ display: 'flex', gap: 8, padding: '6px 0', alignItems: 'flex-start', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ color: s.status === 'done' ? 'var(--done)' : 'var(--muted)', marginTop: 2 }}>{s.status === 'done' ? '✓' : '○'}</span>
                  <div>
                    <div style={{ fontSize: 13, color: s.status === 'done' ? 'var(--muted)' : 'var(--fg)' }}>{s.title}</div>
                    {s.notes && <div style={{ fontSize: 12, color: 'var(--muted)' }}>{s.notes}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
          {task.progress.length > 0 && (
            <div>
              <div style={secHead}>Progress Log ({task.progress.length})</div>
              {[...task.progress].reverse().map((p, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 13 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted-2)', whiteSpace: 'nowrap', minWidth: 80, fontVariantNumeric: 'tabular-nums' }}>
                    {new Date(p.timestamp * 1000).toLocaleTimeString()}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ color: 'var(--fg)', marginBottom: 2 }}>{p.entry}</div>
                    {p.blocker && (
                      <div style={{ fontSize: 12, color: 'var(--blocked)', background: 'var(--blocked-bg)', padding: '4px 8px', borderRadius: 4, marginTop: 4, border: '1px solid var(--blocked-bd)' }}>
                        ⚠ Blocked: {p.blocker.description}
                      </div>
                    )}
                    {p.next_step && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>Next: {p.next_step}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ background: 'var(--surface)', borderLeft: '1px solid var(--border)', padding: 16 }}>
          <SideStat label="Created" value={ts(task.created_at)} />
          <SideStat label="Updated" value={ts(task.updated_at)} />
          <SideStat label="Created by" value={task.created_by} />
          {task.assigned_to && <SideStat label="Assigned to" value={task.assigned_to} mono />}
        </div>
      </div>
    </div>
  )
}

function SideStat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color: 'var(--fg-soft)', fontFamily: mono ? 'var(--font-mono)' : undefined }}>{value}</div>
    </div>
  )
}

const secHead: React.CSSProperties = { fontSize: 13, fontWeight: 600, color: 'var(--fg-soft)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }
const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: 14, outline: 'none', fontFamily: 'inherit' }
const sel: React.CSSProperties = { padding: '4px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface)', fontSize: 13, fontFamily: 'inherit', cursor: 'pointer', color: 'var(--fg)' }
const tagChip: React.CSSProperties = { fontSize: 11, padding: '1px 8px', borderRadius: 10, background: 'var(--surface-raised)', color: 'var(--fg-soft)', fontFamily: 'var(--font-mono)' }
