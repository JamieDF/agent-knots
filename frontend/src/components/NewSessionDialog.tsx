import { useState, useEffect } from 'react'
import { fetchWorkspaces, type Workspace } from '../lib/api'
import { getActiveWorkspace } from '../lib/workspace'

interface Props {
  onStart: (prompt: string, mode: string, workspace: string) => Promise<void>
  onClose: () => void
}

function NewSessionDialog({ onStart, onClose }: Props) {
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState('agent')
  const [workspace, setWorkspace] = useState(getActiveWorkspace())
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
  }, [])

  const handleStart = async () => {
    if (!prompt.trim()) return
    setError(''); setStarting(true)
    try {
      await onStart(prompt.trim(), mode, workspace)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    } finally { setStarting(false) }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 12, padding: 24, maxWidth: 500, width: '100%', margin: 20,
      }} onClick={e => e.stopPropagation()}>
        <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>New Session</h3>

        <label style={labelStyle}>Workspace</label>
        <select value={workspace} onChange={e => setWorkspace(e.target.value)} style={inputStyle}>
          <option value="">No workspace</option>
          {workspaces.map(w => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </select>

        <label style={labelStyle}>Task description</label>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          placeholder="What should the agent do?"
          rows={3}
          autoFocus
          style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }}
          onKeyDown={e => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart()
          }}
        />

        <label style={labelStyle}>Mode</label>
        <select value={mode} onChange={e => setMode(e.target.value)} style={inputStyle}>
          <option value="agent">Agent (autonomous)</option>
          <option value="assistant">Assistant (you drive)</option>
        </select>

        {error && (
          <p style={{ color: 'var(--blocked)', fontSize: 13, marginTop: 8 }}>{error}</p>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button onClick={onClose} className="btn btn-ghost">Cancel</button>
          <button onClick={handleStart} disabled={starting || !prompt.trim()} className="btn"
            style={{
              background: prompt.trim() ? 'var(--fg)' : 'var(--surface-raised)',
              color: prompt.trim() ? 'var(--bg)' : 'var(--muted)', fontWeight: 600,
            }}>
            {starting ? 'Starting...' : 'Start Session'}
          </button>
        </div>
      </div>
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, fontWeight: 600,
  color: 'var(--fg-soft)', marginBottom: 4, marginTop: 12,
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '8px 12px', borderRadius: 6,
  border: '1px solid var(--border)', background: 'var(--bg)',
  color: 'var(--fg)', fontSize: 14, outline: 'none',
}

export default NewSessionDialog
