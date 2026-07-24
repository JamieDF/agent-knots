import { useCallback, useEffect, useState } from 'react'
import { Card, Chip, Field, SectionLabel, inputStyle } from '../../components/primitives'
import { addProvider, deleteProvider, fetchSettings, setDefaultProvider, type ProviderInfo } from '../../lib/api'
import { PROVIDER_PRESETS } from '../../lib/providerPresets'
import { accentTextBtnStyle, deleteBtnStyle, FormDialog } from './shared'

export function ProvidersCard() {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const load = useCallback(() => { fetchSettings().then(s => setProviders(s.providers)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  const handleSetDefault = async (name: string) => { await setDefaultProvider(name); load() }
  const handleDelete = async (name: string) => { try { await deleteProvider(name) } catch { /* synthetic legacy row, nothing to delete server-side */ } load() }

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Model providers</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={accentTextBtnStyle({ marginLeft: 'auto' })}>+ Add provider</button>
      </div>

      {providers.length === 0 && (
        <div style={{ textAlign: 'center', padding: 16, color: 'var(--mut)', fontSize: 13 }}>No providers configured yet.</div>
      )}

      {providers.map(p => (
        <div key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', minWidth: 90 }}>{p.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--ink2)', flex: 1 }}>{p.model}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)', flex: 1 }}>{p.base_url || '—'}</span>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: p.key_set ? 'var(--ok)' : 'var(--mut)' }} title={p.key_set ? 'key set' : 'no key'} />
          {p.is_default ? <Chip color="var(--acc)" soft>DEFAULT</Chip> : (
            <button onClick={() => handleSetDefault(p.name)} style={{ fontSize: 11, fontWeight: 600, color: 'var(--acc)' }}>Set default</button>
          )}
          <button onClick={() => handleDelete(p.name)} style={deleteBtnStyle}>✕</button>
        </div>
      ))}

      <AddProviderDialog open={showAdd} onClose={() => setShowAdd(false)} onSaved={() => { setShowAdd(false); load() }} />
    </Card>
  )
}

function AddProviderDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [preset, setPreset] = useState('minimax')
  const [name, setName] = useState('')
  const [model, setModel] = useState(PROVIDER_PRESETS.minimax.model)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(PROVIDER_PRESETS.minimax.base_url)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const handlePreset = (p: string) => {
    setPreset(p)
    const cfg = PROVIDER_PRESETS[p]
    if (cfg) { setModel(cfg.model); setBaseUrl(cfg.base_url) }
    if (!name) setName(p)
  }

  const reset = () => { setName(''); setApiKey(''); setError(''); handlePreset('minimax') }
  const close = () => { reset(); onClose() }

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true); setError('')
    try {
      await addProvider({ name: name.trim(), model, api_key: apiKey, base_url: baseUrl })
      reset()
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add provider')
    } finally {
      setSaving(false)
    }
  }

  return (
    <FormDialog
      open={open} onClose={close} title="+ Add provider" width={440}
      onSave={handleSave} saveDisabled={!name.trim()} saving={saving} error={error}
      headerExtra={
        <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
          {Object.keys(PROVIDER_PRESETS).map(p => (
            <Chip key={p} color={preset === p ? 'var(--acc)' : undefined} soft={preset === p} onClick={() => handlePreset(p)}>{p}</Chip>
          ))}
        </div>
      }
    >
      <Field label="Name"><input aria-label="Provider name" value={name} onChange={e => setName(e.target.value)} placeholder="minimax" style={inputStyle} /></Field>
      <Field label="Model ID"><input aria-label="Model ID" value={model} onChange={e => setModel(e.target.value)} placeholder="minimax-m2.7" style={inputStyle} /></Field>
      <Field label="API key"><input aria-label="API key" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-..." style={inputStyle} /></Field>
      <Field label="Base URL"><input aria-label="Base URL" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="optional" style={inputStyle} /></Field>
    </FormDialog>
  )
}
