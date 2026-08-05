import { useCallback, useEffect, useState } from 'react'
import { Card, Chip, Field, SectionLabel, Spinner, inputStyle } from '../../components/primitives'
import { addProvider, deleteProvider, fetchSettings, setDefaultProvider, updateProviderModel, fetchProviderModels, type ProviderInfo, type ProviderModel } from '../../lib/api'
import { PROVIDER_PRESETS } from '../../lib/providerPresets'
import { accentTextBtnStyle, deleteBtnStyle, FormDialog } from './shared'

export function ProvidersCard() {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null)

  const load = useCallback(() => { fetchSettings().then(s => setProviders(s.providers)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  const handleSetDefault = async (name: string) => { await setDefaultProvider(name); load() }
  const handleDelete = async (name: string) => {
    try {
      await deleteProvider(name)
    } catch (e) {
      console.warn(`Failed to delete provider "${name}":`, e)
    }
    load()
  }

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
        <ProviderRow
          key={p.name}
          provider={p}
          expanded={expandedProvider === p.name}
          onToggleExpand={() => setExpandedProvider(expandedProvider === p.name ? null : p.name)}
          onSetDefault={() => handleSetDefault(p.name)}
          onDelete={() => handleDelete(p.name)}
          onModelChanged={load}
        />
      ))}

      <AddProviderDialog open={showAdd} onClose={() => setShowAdd(false)} onSaved={() => { setShowAdd(false); load() }} />
    </Card>
  )
}

/** A single provider row with an expandable model browser beneath it.
 *  Clicking the chevron fetches the provider's available models from its
 *  API (GET /v1/models) and lists them inline — click "Use" to set that
 *  model as the provider's active model. */
function ProviderRow({ provider: p, expanded, onToggleExpand, onSetDefault, onDelete, onModelChanged }: {
  provider: ProviderInfo
  expanded: boolean
  onToggleExpand: () => void
  onSetDefault: () => void
  onDelete: () => void
  onModelChanged: () => void
}) {
  const [models, setModels] = useState<ProviderModel[] | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelError, setModelError] = useState('')

  const handleExpand = async () => {
    onToggleExpand()
    if (!expanded && models === null) {
      setLoadingModels(true)
      setModelError('')
      try {
        const res = await fetchProviderModels(p.name)
        setModels(res.models.sort((a, b) => a.id.localeCompare(b.id)))
      } catch (e) {
        setModelError(e instanceof Error ? e.message : 'Failed to fetch models')
        setModels([])
      } finally {
        setLoadingModels(false)
      }
    }
  }

  const handleUseModel = async (modelId: string) => {
    await updateProviderModel(p.name, modelId)
    onModelChanged()
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
        {/* Expand toggle — only show if the provider has a key (can't query without one) */}
        {p.key_set ? (
          <button
            onClick={handleExpand}
            title="Browse available models"
            style={{ fontSize: 10, color: 'var(--mut)', width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'none', border: 'none', cursor: 'pointer', transition: 'transform 0.15s', transform: expanded ? 'rotate(90deg)' : 'none' }}
          >▸</button>
        ) : (
          <span style={{ width: 18 }} />
        )}
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', minWidth: 90 }}>{p.name}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--ink2)', flex: 1 }}>{p.model}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)', flex: 1 }}>{p.base_url || '—'}</span>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: p.key_set ? 'var(--ok)' : 'var(--mut)' }} title={p.key_set ? 'key set' : 'no key'} />
        {p.is_default ? <Chip color="var(--acc)" soft>DEFAULT</Chip> : (
          <button onClick={onSetDefault} style={{ fontSize: 11, fontWeight: 600, color: 'var(--acc)' }}>Set default</button>
        )}
        <button onClick={onDelete} style={deleteBtnStyle}>✕</button>
      </div>

      {/* Expanded model browser */}
      {expanded && (
        <div style={{ padding: '8px 0 12px 28px', borderBottom: '1px solid var(--line)', background: 'var(--card2)' }}>
          {loadingModels && <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}><Spinner /> <span style={{ fontSize: 12, color: 'var(--mut)' }}>Fetching models…</span></div>}
          {modelError && <div style={{ fontSize: 12, color: 'var(--err)', padding: '4px 0' }}>{modelError}</div>}
          {models && models.length > 0 && (
            <>
              <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--mut2)', marginBottom: 6 }}>{models.length} models available</div>
              <div style={{ maxHeight: 240, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
                {models.map(m => (
                  <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 6px', borderRadius: 6, background: m.id === p.model ? 'var(--acc-soft)' : 'transparent' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: m.id === p.model ? 'var(--acc)' : 'var(--ink2)', flex: 1 }}>{m.id}</span>
                    {m.id === p.model ? (
                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--acc)', textTransform: 'uppercase' }}>active</span>
                    ) : (
                      <button onClick={() => handleUseModel(m.id)} style={{ fontSize: 10, fontWeight: 600, color: 'var(--acc)', background: 'none', border: 'none', cursor: 'pointer' }}>Use</button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
          {models && models.length === 0 && !modelError && !loadingModels && (
            <div style={{ fontSize: 12, color: 'var(--mut)' }}>No models returned.</div>
          )}
        </div>
      )}
    </>
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
