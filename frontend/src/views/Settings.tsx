import { useEffect, useState } from 'react'
import { fetchSettings, saveSettings, fetchTools, toggleTool, deleteTool, createTool, fetchWorkspaces, createWorkspace, deleteWorkspace, type ToolInfo, type Workspace } from '../lib/api'

const PROVIDER_PRESETS: Record<string, { model: string; base_url: string }> = {
  openai:    { model: 'gpt-4o-mini', base_url: '' },
  minimax:   { model: 'minimax-m2.7', base_url: 'https://api.minimax.io/v1' },
  anthropic: { model: 'claude-sonnet-4-20250514', base_url: '' },
  ollama:    { model: 'llama3', base_url: 'http://localhost:11434/v1' },
  custom:    { model: '', base_url: '' },
}

export default function SettingsPage() {
  // ── model config ──────────────────────────────────────────────────────
  const [provider, setProvider] = useState('minimax')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [configured, setConfigured] = useState(false)
  const [savingModel, setSavingModel] = useState(false)

  // ── tools ─────────────────────────────────────────────────────────────
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [newToolName, setNewToolName] = useState('')
  const [newToolCmd, setNewToolCmd] = useState('')
  const [newToolDesc, setNewToolDesc] = useState('')
  const [showAddTool, setShowAddTool] = useState(false)

  // ── workspaces ────────────────────────────────────────────────────────
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [newWsId, setNewWsId] = useState('')
  const [newWsName, setNewWsName] = useState('')

  // Load all data.
  useEffect(() => {
    fetchSettings().then(s => {
      setConfigured(s.configured)
      setModel(s.agent.default_model)
      setBaseUrl(s.agent.base_url)
      setApiKey(s.agent.api_key)
      // Detect provider from base URL.
      if (s.agent.base_url.includes('minimax')) setProvider('minimax')
      else if (s.agent.base_url.includes('ollama')) setProvider('ollama')
      else if (s.agent.default_model.includes('claude')) setProvider('anthropic')
      else if (s.agent.base_url) setProvider('custom')
      else setProvider('openai')
    }).catch(() => {})
    fetchTools().then(d => setTools(d.tools)).catch(() => {})
    fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
  }, [])

  const handleProviderChange = (p: string) => {
    setProvider(p)
    const preset = PROVIDER_PRESETS[p]
    if (preset) { setModel(preset.model); setBaseUrl(preset.base_url) }
  }

  const handleSaveModel = async () => {
    setSavingModel(true)
    await saveSettings({ default_model: model, api_key: apiKey, base_url: baseUrl, default_mode: 'agent' })
    setSavingModel(false); setConfigured(true)
  }

  const handleAddTool = async () => {
    if (!newToolName.trim() || !newToolCmd.trim()) return
    await createTool({ name: newToolName.trim(), command: newToolCmd.trim(), description: newToolDesc })
    setNewToolName(''); setNewToolCmd(''); setNewToolDesc(''); setShowAddTool(false)
    fetchTools().then(d => setTools(d.tools)).catch(() => {})
  }

  const handleAddWorkspace = async () => {
    if (!newWsId.trim() || !newWsName.trim()) return
    await createWorkspace({ id: newWsId.trim(), name: newWsName.trim() })
    setNewWsId(''); setNewWsName('')
    fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
  }

  const sections = [
    { id: 'model', label: 'Model Provider' },
    { id: 'tools', label: 'Tools' },
    { id: 'workspaces', label: 'Workspaces' },
  ]
  const [active, setActive] = useState('model')

  return (
    <div style={{ height: '100%', display: 'flex', overflow: 'hidden' }}>
      {/* Left nav */}
      <div style={{ width: 200, background: 'var(--surface)', borderRight: '1px solid var(--border)', padding: 16, flexShrink: 0 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>Settings</h2>
        {sections.map(s => (
          <button key={s.id} onClick={() => setActive(s.id)}
            style={{
              display: 'block', width: '100%', textAlign: 'left', padding: '8px 10px', borderRadius: 6,
              fontSize: 13, border: 0, cursor: 'pointer', fontFamily: 'inherit', marginBottom: 2,
              background: active === s.id ? 'var(--surface-raised)' : 'transparent',
              color: active === s.id ? 'var(--fg)' : 'var(--fg-soft)',
            }}>{s.label}</button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
        {active === 'model' && <div>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Model Provider</h3>

          <div style={{ marginBottom: 16 }}>
            <label style={lbl}>Provider</label>
            <select value={provider} onChange={e => handleProviderChange(e.target.value)} style={inp}>
              <option value="openai">OpenAI</option>
              <option value="minimax">MiniMax</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama (local)</option>
              <option value="custom">Custom</option>
            </select>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={lbl}>Model ID</label>
            <input value={model} onChange={e => setModel(e.target.value)} placeholder="gpt-4o-mini" style={inp} />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={lbl}>API Key</label>
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder={configured ? '•••••••• (unchanged)' : 'sk-...'} style={inp} />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={lbl}>Base URL</label>
            <input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" style={inp} />
          </div>

          <button onClick={handleSaveModel} disabled={savingModel || !model} className="btn"
            style={{ background: model ? 'var(--fg)' : 'var(--surface-raised)', color: model ? 'var(--bg)' : 'var(--muted)', fontWeight: 600, padding: '8px 16px' }}>
            {savingModel ? 'Saving...' : 'Save'}
          </button>
          {configured && <span style={{ marginLeft: 10, fontSize: 12, color: 'var(--done)' }}>✓ Configured</span>}
        </div>}

        {active === 'tools' && <div>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Tools</h3>
          <div style={{ marginBottom: 16 }}>
            {tools.filter(t => t.builtin).map(t => (
              <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 13 }}>
                <span style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12 }}>{t.name}</span>
                <span style={{ fontSize: 10, color: 'var(--info)', background: 'oklch(68% 0.12 235 / 0.1)', padding: '1px 6px', borderRadius: 4 }}>built-in</span>
                <button onClick={async () => { await toggleTool(t.name); fetchTools().then(d => setTools(d.tools)).catch(() => {}) }}
                  style={toggleBtn(t.enabled)}>{t.enabled ? 'On' : 'Off'}</button>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 8 }}>
            {tools.filter(t => !t.builtin).map(t => (
              <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 13 }}>
                <span style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12 }}>{t.name}</span>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>{t.description || ''}</span>
                <button onClick={async () => { await toggleTool(t.name); fetchTools().then(d => setTools(d.tools)).catch(() => {}) }}
                  style={toggleBtn(t.enabled)}>{t.enabled ? 'On' : 'Off'}</button>
                <button onClick={async () => { await deleteTool(t.name); fetchTools().then(d => setTools(d.tools)).catch(() => {}) }}
                  style={{ color: 'var(--blocked)', cursor: 'pointer', border: 0, background: 'none', fontSize: 14 }}>✕</button>
              </div>
            ))}
          </div>
          {showAddTool ? (
            <div style={{ marginTop: 12, padding: 12, background: 'var(--surface-raised)', borderRadius: 8 }}>
              <input placeholder="Tool name" value={newToolName} onChange={e => setNewToolName(e.target.value)} style={{ ...inp, marginBottom: 8 }} />
              <input placeholder="Shell command" value={newToolCmd} onChange={e => setNewToolCmd(e.target.value)} style={{ ...inp, marginBottom: 8 }} />
              <input placeholder="Description (optional)" value={newToolDesc} onChange={e => setNewToolDesc(e.target.value)} style={{ ...inp, marginBottom: 8 }} />
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={handleAddTool} className="btn" style={{ background: 'var(--info)', color: 'var(--bg)', fontWeight: 600, fontSize: 12 }}>Add</button>
                <button onClick={() => setShowAddTool(false)} className="btn btn-ghost" style={{ fontSize: 12 }}>Cancel</button>
              </div>
            </div>
          ) : (
            <button onClick={() => setShowAddTool(true)} className="btn" style={{ marginTop: 12, background: 'var(--surface-raised)', color: 'var(--fg-soft)', fontSize: 12 }}>
              + Add custom tool
            </button>
          )}
        </div>}

        {active === 'workspaces' && <div>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Workspaces</h3>
          {workspaces.map(w => (
            <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 13 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-soft)' }}>{w.id}</span>
              <span style={{ flex: 1 }}>{w.name}</span>
              <button onClick={async () => { await deleteWorkspace(w.id); fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {}) }}
                style={{ color: 'var(--blocked)', cursor: 'pointer', border: 0, background: 'none', fontSize: 14 }}>✕</button>
            </div>
          ))}
          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <input placeholder="Workspace ID" value={newWsId} onChange={e => setNewWsId(e.target.value)} style={{ ...inp, flex: 1 }} />
            <input placeholder="Name" value={newWsName} onChange={e => setNewWsName(e.target.value)} style={{ ...inp, flex: 1 }} />
            <button onClick={handleAddWorkspace} className="btn" style={{ background: 'var(--info)', color: 'var(--bg)', fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap' }}>Add</button>
          </div>
        </div>}
      </div>
    </div>
  )
}

function toggleBtn(on: boolean): React.CSSProperties {
  return {
    fontSize: 11, padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border)',
    background: on ? 'oklch(72% 0.16 155 / 0.1)' : 'var(--surface-raised)',
    color: on ? 'var(--running)' : 'var(--muted)', cursor: 'pointer', fontFamily: 'inherit',
  }
}

const lbl: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--fg-soft)', marginBottom: 4 }
const inp: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: 14, outline: 'none', fontFamily: 'inherit' }
