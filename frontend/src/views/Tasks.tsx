import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchTasks, createTask, type TaskSummary } from '../lib/api'

const STATUS_ICONS: Record<string, { icon: string; color: string; label: string }> = {
  draft:      { icon: '○', color: 'var(--muted-2)', label: 'Draft' },
  open:       { icon: '◌', color: 'var(--fg-soft)', label: 'Open' },
  planned:    { icon: '◔', color: 'var(--info)', label: 'Planned' },
  in_progress:{ icon: '●', color: 'var(--running)', label: 'In Progress' },
  blocked:    { icon: '⚠', color: 'var(--blocked)', label: 'Blocked' },
  review:     { icon: '◉', color: 'oklch(70% 0.14 295)', label: 'Review' },
  done:       { icon: '✓', color: 'var(--done)', label: 'Done' },
  abandoned:  { icon: '✗', color: 'var(--muted-2)', label: 'Abandoned' },
}

const PRIORITY_ORDER: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 }

function statusChip(status: string) {
  const s = STATUS_ICONS[status] || STATUS_ICONS.open
  return <span style={{ color: s.color, fontSize: 12, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
    {s.icon} {s.label}
  </span>
}

function progressBar(current: number, total: number) {
  const pct = total > 0 ? Math.round((current / total) * 100) : 0
  return <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
    <div style={{ width: 60, height: 4, background: 'var(--surface-raised)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: 'var(--running)', borderRadius: 2, transition: 'width 0.3s' }} />
    </div>
    <span style={{ fontSize: 11, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>{current}/{total}</span>
  </div>
}

export default function Tasks() {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const data = await fetchTasks({ status: statusFilter || undefined, limit: 50 })
        if (mounted) setTasks(data.tasks.sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 2) - (PRIORITY_ORDER[b.priority] ?? 2)))
      } catch { /* ignore */ }
    }
    load()
    const interval = setInterval(load, 5000)
    return () => { mounted = false; clearInterval(interval) }
  }, [statusFilter])

  return (
    <>
      <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
        {/* Filter sidebar */}
        <div style={{ width: 200, background: 'var(--surface)', borderRight: '1px solid var(--border)', padding: 16, overflowY: 'auto', flexShrink: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>Status</div>
          {['', ...Object.keys(STATUS_ICONS)].map(s => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              style={{
                display: 'block', width: '100%', textAlign: 'left', padding: '4px 8px', borderRadius: 4,
                fontSize: 13, color: statusFilter === s ? 'var(--fg)' : 'var(--fg-soft)',
                background: statusFilter === s ? 'var(--surface-raised)' : 'transparent',
                marginBottom: 2, cursor: 'pointer', border: 0, fontFamily: 'inherit',
              }}
            >
              {s ? statusChip(s) : 'All'}
            </button>
          ))}

          <div style={{ marginTop: 20 }}>
            <button
              onClick={() => setShowCreate(true)}
              style={{
                width: '100%', padding: '8px', borderRadius: 6, border: '1px solid var(--border)',
                background: 'var(--info)', color: 'var(--bg)', fontSize: 13, fontWeight: 600, cursor: 'pointer',
              }}
            >
              + New Task
            </button>
          </div>
        </div>

        {/* Task table */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 0 }}>
          {tasks.length === 0 && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--muted)', fontSize: 14 }}>
              No tasks yet. Create one to get started.
            </div>
          )}
          {tasks.map(t => (
            <div
              key={t.id}
              onClick={() => navigate(`/tasks/${t.id}`)}
              style={{
                display: 'grid', gridTemplateColumns: '1fr 120px 100px 100px 100px',
                gap: 12, padding: '10px 20px', borderBottom: '1px solid var(--border-subtle)',
                alignItems: 'center', cursor: 'pointer', fontSize: 13,
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >
              <div>
                <div style={{ fontWeight: 500, color: 'var(--fg)', marginBottom: 2 }}>{t.title}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>{t.id}</div>
              </div>
              <div>{statusChip(t.status)}</div>
              <div style={{ color: 'var(--fg-soft)', fontSize: 12, textTransform: 'capitalize' }}>{t.priority}</div>
              <div>{progressBar(t.progress_count, t.steps_count || t.criteria_count)}</div>
              <div style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                {new Date(t.updated_at * 1000).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Create task dialog */}
      {showCreate && <CreateTaskDialog onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false) }} />}
    </>
  )
}

// ── inline create dialog ─────────────────────────────────────────────────────

function CreateTaskDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('medium')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const handleCreate = async () => {
    if (!title.trim()) return
    setError(''); setSaving(true)
    try {
      await createTask({ title: title.trim(), description, priority })
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally { setSaving(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }} onClick={onClose}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 24, maxWidth: 500, width: '100%', margin: 20 }} onClick={e => e.stopPropagation()}>
        <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>New Task</h3>

        <label style={lbl}>Title</label>
        <input autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="What needs to be done?" style={inp} onKeyDown={e => { if (e.key === 'Enter') handleCreate() }} />

        <label style={lbl}>Description (optional)</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }} />

        <label style={lbl}>Priority</label>
        <select value={priority} onChange={e => setPriority(e.target.value)} style={inp}>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="urgent">Urgent</option>
        </select>

        {error && <p style={{ color: 'var(--blocked)', fontSize: 13, marginTop: 8 }}>{error}</p>}

        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button onClick={onClose} className="btn btn-ghost">Cancel</button>
          <button onClick={handleCreate} disabled={saving || !title.trim()} className="btn"
            style={{ background: title.trim() ? 'var(--fg)' : 'var(--surface-raised)', color: title.trim() ? 'var(--bg)' : 'var(--muted)', fontWeight: 600 }}>
            {saving ? 'Creating...' : 'Create Task'}
          </button>
        </div>
      </div>
    </div>
  )
}

const lbl: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--fg-soft)', marginBottom: 4, marginTop: 12 }
const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: 14, outline: 'none' }
