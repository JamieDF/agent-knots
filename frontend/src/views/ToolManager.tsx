import { useEffect, useState } from 'react'
import { fetchTools, createTool, deleteTool, toggleTool, type ToolInfo } from '../lib/api'

export default function ToolManager() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    fetchTools().then(d => setTools(d.tools)).catch(() => {})
  }, [refresh])

  const builtins = tools.filter(t => t.builtin)
  const customs = tools.filter(t => !t.builtin)

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700 }}>Tools</h2>
        <button onClick={() => setShowAdd(true)} className="btn" style={{ background: 'var(--info)', color: 'var(--bg)', fontWeight: 600 }}>
          + Custom Tool
        </button>
      </div>

      {/* Built-in tools */}
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
          Built-in ({builtins.length})
        </h3>
        {builtins.map(t => (
          <ToolRow key={t.name} tool={t} onToggle={() => { toggleTool(t.name).then(() => setRefresh(r => r + 1)) }} />
        ))}
      </div>

      {/* Custom tools */}
      <div>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
          Custom ({customs.length})
        </h3>
        {customs.length === 0 && (
          <p style={{ color: 'var(--muted)', fontSize: 13 }}>No custom tools yet. Create one to extend your agents.</p>
        )}
        {customs.map(t => (
          <ToolRow key={t.name} tool={t} onToggle={() => { toggleTool(t.name).then(() => setRefresh(r => r + 1)) }}
            onDelete={() => { deleteTool(t.name).then(() => setRefresh(r => r + 1)) }} />
        ))}
      </div>

      {showAdd && <AddToolDialog onClose={() => setShowAdd(false)} onCreated={() => { setShowAdd(false); setRefresh(r => r + 1) }} />}
    </div>
  )
}

function ToolRow({ tool, onToggle, onDelete }: { tool: ToolInfo; onToggle: () => void; onDelete?: () => void }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0',
      borderBottom: '1px solid var(--border-subtle)', fontSize: 13,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, color: 'var(--fg)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{tool.name}</span>
          {tool.builtin && <span style={{ fontSize: 10, color: 'var(--info)', background: 'oklch(68% 0.12 235 / 0.1)', padding: '1px 6px', borderRadius: 4 }}>built-in</span>}
        </div>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 2 }}>{tool.description || 'No description'}</div>
      </div>
      <button onClick={onToggle} style={{
        fontSize: 11, padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border)',
        background: tool.enabled ? 'oklch(72% 0.16 155 / 0.1)' : 'var(--surface-raised)',
        color: tool.enabled ? 'var(--running)' : 'var(--muted)',
        cursor: 'pointer', fontFamily: 'inherit',
      }}>
        {tool.enabled ? 'Enabled' : 'Disabled'}
      </button>
      {onDelete && (
        <button onClick={onDelete} style={{ color: 'var(--blocked)', fontSize: 12, cursor: 'pointer', border: 0, background: 'none' }} title="Delete">
          ✕
        </button>
      )}
    </div>
  )
}

function AddToolDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [command, setCommand] = useState('')
  const [params, setParams] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const handleCreate = async () => {
    if (!name.trim() || !command.trim()) return
    setError(''); setSaving(true)
    try {
      let paramList: any[] = []
      if (params.trim()) {
        paramList = params.split(',').map(p => {
          const [pn, pt = 'string'] = p.trim().split(':')
          return { name: pn.trim(), type: pt.trim(), description: '' }
        })
      }
      await createTool({ name: name.trim(), description: desc, command: command.trim(), parameters: paramList })
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally { setSaving(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }} onClick={onClose}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 24, maxWidth: 500, width: '100%', margin: 20 }} onClick={e => e.stopPropagation()}>
        <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>New Custom Tool</h3>

        <label style={lbl}>Name</label>
        <input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="my_tool" style={inp} />

        <label style={lbl}>Description</label>
        <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="What does this tool do?" style={inp} />

        <label style={lbl}>Shell Command</label>
        <textarea value={command} onChange={e => setCommand(e.target.value)} placeholder="echo Hello {name}" rows={2} style={{ ...inp, resize: 'vertical', fontFamily: 'var(--font-mono)' }} />

        <label style={lbl}>Parameters (optional)</label>
        <input value={params} onChange={e => setParams(e.target.value)} placeholder="name:string, path:string" style={inp} />
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Format: name:type, name:type. Use {'{name}'} in the command.</div>

        {error && <p style={{ color: 'var(--blocked)', fontSize: 13, marginTop: 8 }}>{error}</p>}

        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button onClick={onClose} className="btn btn-ghost">Cancel</button>
          <button onClick={handleCreate} disabled={saving || !name.trim() || !command.trim()} className="btn"
            style={{ background: name.trim() && command.trim() ? 'var(--fg)' : 'var(--surface-raised)', color: name.trim() && command.trim() ? 'var(--bg)' : 'var(--muted)', fontWeight: 600 }}>
            {saving ? 'Creating...' : 'Create Tool'}
          </button>
        </div>
      </div>
    </div>
  )
}

const lbl: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--fg-soft)', marginBottom: 4, marginTop: 12 }
const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: 14, outline: 'none', fontFamily: 'inherit' }
