import { useState, useEffect } from 'react'
import { fetchSettings, saveSettings, type SettingsResponse } from '../lib/api'

interface Props {
  onComplete: () => void
}

const PRESETS: Record<string, { model: string; base_url: string }> = {
  openai: { model: 'openai/gpt-4o-mini', base_url: '' },
  minimax: { model: 'minimax-m2.7', base_url: 'https://api.minimax.io/v1' },
  anthropic: { model: 'anthropic/claude-sonnet-4-20250514', base_url: '' },
  ollama: { model: 'ollama/llama3', base_url: 'http://localhost:11434/v1' },
  custom: { model: '', base_url: '' },
}

function SetupWizard({ onComplete }: Props) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [provider, setProvider] = useState('openai')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchSettings().then(s => {
      setSettings(s)
      // Pre-fill from existing settings.
      if (s.agent.base_url) {
        // Detect provider from base URL
        if (s.agent.base_url.includes('minimax')) setProvider('minimax')
        else if (s.agent.base_url.includes('ollama')) setProvider('ollama')
        else setProvider('custom')
      }
      setModel(s.agent.default_model)
      setBaseUrl(s.agent.base_url)
      if (s.agent.api_key) setApiKey(s.agent.api_key) // masked
    }).catch(() => {})
  }, [])

  const handleProviderChange = (p: string) => {
    setProvider(p)
    const preset = PRESETS[p]
    if (preset) {
      setModel(preset.model)
      setBaseUrl(preset.base_url)
    }
  }

  const handleSave = async () => {
    setError('')
    setSaving(true)
    try {
      await saveSettings({
        default_model: model,
        api_key: apiKey,
        base_url: baseUrl,
        default_mode: 'agent',
      })
      onComplete()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100%', padding: 20,
    }}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 12, padding: 32, maxWidth: 480, width: '100%',
      }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>⚡ Welcome to agentjam</h2>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 24 }}>
          Configure your model provider to get started.
        </p>

        {/* Provider */}
        <label style={labelStyle}>Provider</label>
        <select
          value={provider}
          onChange={e => handleProviderChange(e.target.value)}
          style={inputStyle}
        >
          <option value="openai">OpenAI</option>
          <option value="minimax">MiniMax</option>
          <option value="anthropic">Anthropic</option>
          <option value="ollama">Ollama (local)</option>
          <option value="custom">Custom</option>
        </select>

        {/* Model */}
        <label style={labelStyle}>Model</label>
        <input
          type="text"
          value={model}
          onChange={e => setModel(e.target.value)}
          placeholder="openai/gpt-4o-mini"
          style={inputStyle}
        />

        {/* API Key */}
        <label style={labelStyle}>API Key</label>
        <input
          type="password"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder={settings?.agent.api_key ? '•••••••• (unchanged)' : 'sk-...'}
          style={inputStyle}
        />

        {/* Base URL */}
        <label style={labelStyle}>Base URL (optional)</label>
        <input
          type="text"
          value={baseUrl}
          onChange={e => setBaseUrl(e.target.value)}
          placeholder="https://api.openai.com/v1"
          style={inputStyle}
        />

        {error && (
          <p style={{ color: 'var(--blocked)', fontSize: 13, marginBottom: 12 }}>{error}</p>
        )}

        <button
          onClick={handleSave}
          disabled={saving || !model}
          style={{
            width: '100%', padding: '10px', borderRadius: 8, border: 'none',
            fontSize: 14, fontWeight: 600, cursor: 'pointer',
            background: model ? 'var(--fg)' : 'var(--surface-raised)',
            color: model ? 'var(--bg)' : 'var(--muted)',
            marginTop: 8,
          }}
        >
          {saving ? 'Saving...' : 'Save & Continue'}
        </button>

        <p style={{ color: 'var(--muted)', fontSize: 11, marginTop: 16, textAlign: 'center' }}>
          Your API key is stored encrypted at ~/.agentjam/settings.yaml
        </p>
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
  fontFamily: 'inherit',
}

export default SetupWizard
