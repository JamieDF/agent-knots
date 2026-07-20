import { useState } from 'react'
import { createTask } from '../lib/api'

interface Props {
  onClose: () => void
  onCreated: () => void
}

export default function CreateTaskDialog({ onClose, onCreated }: Props) {
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
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={e => e.stopPropagation()}>
        <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>New Task</h3>

        <label style={lbl}>Title</label>
        <input autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="What needs to be done?" style={inp}
          onKeyDown={e => { if (e.key === 'Enter') handleCreate() }} />

        <label style={lbl}>Description (optional)</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2}
          style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }} />

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

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }
const dialog: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 24, maxWidth: 500, width: '100%', margin: 20 }
const lbl: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--fg-soft)', marginBottom: 4, marginTop: 12 }
const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: 14, outline: 'none' }
