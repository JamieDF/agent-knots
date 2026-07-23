import { useState, useEffect } from 'react'
import { Card, Chip, Field, inputStyle } from './primitives'
import { fetchSettings, saveSettings, type SettingsResponse } from '../lib/api'
import { PROVIDER_PRESETS } from '../lib/providerPresets'

interface Props {
  onComplete: () => void
  onSkip: () => void
}

/** First-run setup wizard — shown inline in place of the Dashboard
 * until a model provider is configured. See
 * design_handoff_atelier_cockpit/README.md §9. */
function SetupWizard({ onComplete, onSkip }: Props) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [preset, setPreset] = useState('minimax')
  const [model, setModel] = useState(PROVIDER_PRESETS.minimax.model)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(PROVIDER_PRESETS.minimax.base_url)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchSettings().then(s => {
      setSettings(s)
      // AgentSettings.default_model has a non-empty dataclass default
      // ("openai/gpt-4o-mini") even on a totally fresh install, so it
      // isn't safe to treat as "existing settings to prefill from"
      // unless the user has actually entered something — otherwise the
      // wizard shows the MiniMax chip selected but the stale OpenAI
      // default sitting in the model field. base_url/api_key both
      // default to "", so either being non-empty is a real signal even
      // if the user hasn't finished (e.g. set a URL but no key yet).
      if (!s.agent.base_url && !s.agent.api_key) return
      if (s.agent.base_url) {
        if (s.agent.base_url.includes('minimax')) setPreset('minimax')
        else if (s.agent.base_url.includes('ollama')) setPreset('ollama')
        else setPreset('custom')
      } else {
        setPreset('custom')
      }
      setModel(s.agent.default_model)
      setBaseUrl(s.agent.base_url)
      setApiKey(s.agent.api_key) // masked
    }).catch(() => {})
  }, [])

  const handlePreset = (p: string) => {
    setPreset(p)
    const cfg = PROVIDER_PRESETS[p]
    if (cfg) { setModel(cfg.model); setBaseUrl(cfg.base_url) }
  }

  const handleSave = async () => {
    setError('')
    setSaving(true)
    try {
      await saveSettings({ default_model: model, api_key: apiKey, base_url: baseUrl, default_mode: 'agent' })
      onComplete()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 20 }}>
      <Card style={{ width: 520, maxWidth: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <div style={{
            width: 48, height: 48, borderRadius: 12, background: 'var(--card2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 22, margin: '0 auto 12px',
          }}>⚡</div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>Welcome to agent-knots</div>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
            Configure a model provider to get started.
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap', justifyContent: 'center' }}>
          {Object.keys(PROVIDER_PRESETS).map(p => (
            <Chip key={p} color={preset === p ? 'var(--acc)' : undefined} soft={preset === p} onClick={() => handlePreset(p)}>
              {p}
            </Chip>
          ))}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label="Model ID">
            <input aria-label="Model ID" value={model} onChange={e => setModel(e.target.value)} placeholder="minimax-m2.7" style={inputStyle} />
          </Field>
          <Field label="API key">
            <input
              aria-label="API key"
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder={settings?.agent.api_key ? '•••••••• (unchanged)' : 'sk-...'}
              style={inputStyle}
            />
          </Field>
          {preset === 'custom' && (
            <Field label="Base URL">
              <input aria-label="Base URL" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" style={inputStyle} />
            </Field>
          )}

          {error && <div style={{ fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}

          <div style={{ fontSize: 10.5, color: 'var(--mut)', textAlign: 'center' }}>
            Stored in plain text at ~/.agent-knots/settings.yaml. For encrypted
            credential storage, use the Vault instead.
          </div>

          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button onClick={onSkip} style={{ flex: 1, padding: '9px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>
              Skip
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !model}
              style={{
                flex: 2, padding: '9px 14px', borderRadius: 8, fontSize: 13, fontWeight: 700,
                background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || !model ? 0.6 : 1,
              }}
            >
              {saving ? 'Saving…' : 'Finish setup →'}
            </button>
          </div>
        </div>
      </Card>
    </div>
  )
}

export default SetupWizard
