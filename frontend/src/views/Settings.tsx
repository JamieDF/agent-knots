import { useEffect, useState, useCallback } from 'react'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip, Toggle, SectionLabel, Dialog } from '../components/primitives'
import WorkspaceDialog from '../components/WorkspaceDialog'
import {
  fetchSettings, addProvider, deleteProvider, setDefaultProvider, saveIntegrations,
  fetchUsage, fetchPolicies, updatePolicy,
  fetchMcpServers, addMcpServer, toggleMcpServer, deleteMcpServer,
  fetchTools, createTool, deleteTool, toggleTool,
  fetchWorkspaces, deleteWorkspace,
  type ProviderInfo, type IntegrationsInfo, type UsageSummary, type PolicyInfo,
  type McpServerInfo, type ToolInfo, type Workspace,
} from '../lib/api'
import { PROVIDER_PRESETS } from '../lib/providerPresets'

/** Settings screen — one 800px scrolling column of cards, in the order
 * specified by design_handoff_atelier_cockpit/README.md §8. First-run
 * flow previews (item 8) are deferred to Phase 6, which is what
 * actually builds the setup-wizard route these would link to. */
function SettingsPage() {
  return (
    <DeskLayout width={800}>
      <UsageCard />
      <ProvidersCard />
      <ToolsCard />
      <PoliciesCard />
      <McpServersCard />
      <IntegrationsCard />
      <WorkspacesCard />
    </DeskLayout>
  )
}

// ── 1. Usage ─────────────────────────────────────────────────────────────────

function UsageCard() {
  const [usage, setUsage] = useState<UsageSummary | null>(null)

  useEffect(() => { fetchUsage().then(setUsage).catch(() => {}) }, [])

  if (!usage) return null

  const maxProviderTokens = Math.max(1, ...usage.by_provider.map(p => p.tokens))
  const maxTaskTokens = Math.max(1, ...usage.top_tasks.map(t => t.tokens))

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionLabel>Usage</SectionLabel>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', margin: '4px 0 14px' }}>
        Token counts are exact; cost is an estimate from each provider's pricing.
      </div>
      <div style={{ display: 'flex', gap: 24, marginBottom: 16 }}>
        <Stat label="Tokens today" value={usage.today.tokens.toLocaleString()} />
        <Stat label="Tokens this month" value={usage.month.tokens.toLocaleString()} />
        <Stat label="~$ today" value={`$${usage.today.cost_usd.toFixed(2)}`} />
        <Stat label="~$ this month" value={`$${usage.month.cost_usd.toFixed(2)}`} />
      </div>

      {usage.by_provider.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--mut)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>By provider</div>
          {usage.by_provider.map(p => (
            <BarRow key={p.provider} label={p.provider} value={p.tokens} max={maxProviderTokens} suffix={`${p.tokens.toLocaleString()} tok · ~$${p.cost_usd.toFixed(2)}`} />
          ))}
        </div>
      )}

      {usage.top_tasks.length > 0 && (
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--mut)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Top tasks by tokens</div>
          {usage.top_tasks.map(t => (
            <BarRow key={t.task_id} label={t.task_id} value={t.tokens} max={maxTaskTokens} suffix={`${t.tokens.toLocaleString()} tok`} />
          ))}
        </div>
      )}
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--ink)' }}>{value}</div>
      <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{label}</div>
    </div>
  )
}

function BarRow({ label, value, max, suffix }: { label: string; value: number; max: number; suffix: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink2)', minWidth: 90 }}>{label}</span>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--card2)', overflow: 'hidden' }}>
        <div style={{ width: `${Math.max(2, (value / max) * 100)}%`, height: '100%', background: 'var(--acc)' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)', minWidth: 120, textAlign: 'right' }}>{suffix}</span>
    </div>
  )
}

// ── 2. Model providers ───────────────────────────────────────────────────────

function ProvidersCard() {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const load = useCallback(() => { fetchSettings().then(s => setProviders(s.providers)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  const handleSetDefault = async (name: string) => { await setDefaultProvider(name); load() }
  const handleDelete = async (name: string) => { try { await deleteProvider(name) } catch { /* synthetic legacy row, nothing to delete server-side */ } load() }

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Model providers</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 600, color: 'var(--acc)' }}>+ Add provider</button>
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
          <button onClick={() => handleDelete(p.name)} style={{ color: 'var(--err)', fontSize: 14 }}>✕</button>
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
    <Dialog open={open} onClose={() => { reset(); onClose() }} width={440}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>+ Add provider</div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
        {Object.keys(PROVIDER_PRESETS).map(p => (
          <Chip key={p} color={preset === p ? 'var(--acc)' : undefined} soft={preset === p} onClick={() => handlePreset(p)}>{p}</Chip>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Name"><input aria-label="Provider name" value={name} onChange={e => setName(e.target.value)} placeholder="minimax" style={inputStyle} /></Field>
        <Field label="Model ID"><input aria-label="Model ID" value={model} onChange={e => setModel(e.target.value)} placeholder="minimax-m2.7" style={inputStyle} /></Field>
        <Field label="API key"><input aria-label="API key" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-..." style={inputStyle} /></Field>
        <Field label="Base URL"><input aria-label="Base URL" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="optional" style={inputStyle} /></Field>
        {error && <div style={{ fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={() => { reset(); onClose() }} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || !name.trim()} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || !name.trim() ? 0.6 : 1 }}>
            {saving ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

// ── 3. Tools ─────────────────────────────────────────────────────────────────

function ToolsCard() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const load = useCallback(() => { fetchTools().then(d => setTools(d.tools)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Tools</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 600, color: 'var(--acc)' }}>+ Custom tool</button>
      </div>
      {tools.map(t => (
        <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--ink)', minWidth: 120 }}>{t.name}</span>
          <span style={{ fontSize: 11.5, color: 'var(--mut)', flex: 1 }}>{t.description}</span>
          <Chip soft color={t.builtin ? 'var(--mut)' : 'var(--acc)'}>{t.builtin ? 'BUILT-IN' : 'CUSTOM'}</Chip>
          <Toggle checked={t.enabled} onChange={async () => { await toggleTool(t.name); load() }} />
          {!t.builtin && <button onClick={async () => { await deleteTool(t.name); load() }} style={{ color: 'var(--err)', fontSize: 14 }}>✕</button>}
        </div>
      ))}
      <CustomToolDialog open={showAdd} onClose={() => setShowAdd(false)} onSaved={() => { setShowAdd(false); load() }} />
    </Card>
  )
}

function CustomToolDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [command, setCommand] = useState('')
  const [params, setParams] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const reset = () => { setName(''); setDescription(''); setCommand(''); setParams(''); setError('') }

  const parseParams = () => params.split(',').map(s => s.trim()).filter(Boolean).map(entry => {
    const [pname, ptype] = entry.split(':').map(s => s.trim())
    return { name: pname, type: ptype || 'string', description: '' }
  })

  const handleSave = async () => {
    if (!name.trim() || !command.trim()) return
    setSaving(true); setError('')
    try {
      await createTool({ name: name.trim(), description, command: command.trim(), parameters: parseParams() })
      reset()
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create tool')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={() => { reset(); onClose() }} width={460}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>+ Custom tool</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Name"><input aria-label="Tool name" value={name} onChange={e => setName(e.target.value)} placeholder="run_tests" style={inputStyle} /></Field>
        <Field label="Description"><input aria-label="Tool description" value={description} onChange={e => setDescription(e.target.value)} placeholder="optional" style={inputStyle} /></Field>
        <Field label="Shell command"><input aria-label="Shell command" value={command} onChange={e => setCommand(e.target.value)} placeholder="pytest {path} -v" style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }} /></Field>
        <Field label="Params"><input aria-label="Params" value={params} onChange={e => setParams(e.target.value)} placeholder="path:string, verbose:boolean" style={inputStyle} /></Field>
        {error && <div style={{ fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={() => { reset(); onClose() }} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || !name.trim() || !command.trim()} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || !name.trim() || !command.trim() ? 0.6 : 1 }}>
            {saving ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

// ── 4. Policies ──────────────────────────────────────────────────────────────

function PoliciesCard() {
  const [policies, setPolicies] = useState<PolicyInfo[]>([])
  const load = useCallback(() => { fetchPolicies().then(d => setPolicies(d.policies)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionLabel>Policies</SectionLabel>
      <div style={{ fontSize: 11, color: 'var(--mut)', margin: '4px 0 10px' }}>
        Only the spend cap is actually enforced today — the rest are configured for later.
      </div>
      {policies.map(p => (
        <div key={p.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{p.label}</div>
            <div style={{ fontSize: 11, color: 'var(--mut)' }}>{p.description}</div>
          </div>
          {p.key === 'spend_cap' && (
            <input
              aria-label="Spend cap value"
              value={p.value}
              onChange={e => setPolicies(prev => prev.map(x => x.key === p.key ? { ...x, value: e.target.value } : x))}
              onBlur={async e => { await updatePolicy(p.key, { value: e.target.value }); load() }}
              style={{ ...inputStyle, width: 70, textAlign: 'right' }}
            />
          )}
          {!p.enforced && <Chip soft color="var(--mut)">not enforced</Chip>}
          <Toggle checked={p.enabled} onChange={async checked => { await updatePolicy(p.key, { enabled: checked }); load() }} />
        </div>
      ))}
    </Card>
  )
}

// ── 5. MCP servers ───────────────────────────────────────────────────────────

function McpServersCard() {
  const [servers, setServers] = useState<McpServerInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')

  const load = useCallback(() => { fetchMcpServers().then(d => setServers(d.servers)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  const handleAdd = async () => {
    if (!name.trim()) return
    await addMcpServer({ name: name.trim(), url })
    setName(''); setUrl(''); setShowAdd(false)
    load()
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>MCP servers</SectionLabel>
      </div>
      {servers.length === 0 && !showAdd && (
        <div style={{ textAlign: 'center', padding: 12, color: 'var(--mut)', fontSize: 13 }}>No MCP servers configured.</div>
      )}
      {servers.map(s => (
        <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', flex: 1 }}>{s.name}</span>
          <span style={{ fontSize: 11, color: 'var(--mut)' }}>{s.tool_count} tools exposed</span>
          <Toggle checked={s.enabled} onChange={async checked => { await toggleMcpServer(s.name, checked); load() }} />
          <button onClick={async () => { await deleteMcpServer(s.name); load() }} style={{ color: 'var(--err)', fontSize: 14 }}>✕</button>
        </div>
      ))}
      {showAdd ? (
        <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
          <input aria-label="MCP server name" value={name} onChange={e => setName(e.target.value)} placeholder="filesystem" style={{ ...inputStyle, flex: 1 }} />
          <input aria-label="MCP server URL" value={url} onChange={e => setUrl(e.target.value)} placeholder="stdio://..." style={{ ...inputStyle, flex: 1 }} />
          <button onClick={handleAdd} style={{ fontSize: 12, fontWeight: 600, color: 'var(--acc-ink)', background: 'var(--acc)', padding: '6px 12px', borderRadius: 8, whiteSpace: 'nowrap' }}>Add</button>
        </div>
      ) : (
        <button onClick={() => setShowAdd(true)} style={{ marginTop: 10, fontSize: 12, fontWeight: 600, color: 'var(--acc)' }}>+ Add MCP server</button>
      )}
    </Card>
  )
}

// ── 6. Integrations ──────────────────────────────────────────────────────────

function IntegrationsCard() {
  const [integrations, setIntegrations] = useState<IntegrationsInfo | null>(null)
  useEffect(() => { fetchSettings().then(s => setIntegrations(s.integrations)).catch(() => {}) }, [])

  if (!integrations) return null

  const update = async (patch: Partial<IntegrationsInfo>) => {
    setIntegrations(prev => prev ? { ...prev, ...patch } : prev)
    await saveIntegrations(patch)
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionLabel>Integrations</SectionLabel>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>GitHub</div>
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>Not connected — open a PR automatically when a task enters review.</div>
        </div>
        <Toggle checked={integrations.github_pr_on_review} onChange={checked => update({ github_pr_on_review: checked })} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Phone push</div>
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>Config only — no push infrastructure is wired up yet.</div>
        </div>
        <Toggle checked={integrations.phone_push} onChange={checked => update({ phone_push: checked })} />
      </div>
    </Card>
  )
}

// ── 7. Workspaces ────────────────────────────────────────────────────────────

function WorkspacesCard() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [editing, setEditing] = useState<Workspace | null>(null)
  const [showAdd, setShowAdd] = useState(false)

  const load = useCallback(() => { fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Workspaces</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 600, color: 'var(--acc)' }}>+ Add workspace</button>
      </div>
      {workspaces.map(w => (
        <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)', minWidth: 80 }}>{w.id}</span>
          <span style={{ fontSize: 13, color: 'var(--ink)', flex: 1 }}>{w.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>{w.repository || '—'}</span>
          <Chip mono soft>{w.runtime || 'global'}</Chip>
          <button onClick={() => setEditing(w)} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}>Edit</button>
          <button onClick={async () => { await deleteWorkspace(w.id); load() }} style={{ color: 'var(--err)', fontSize: 14 }}>✕</button>
        </div>
      ))}
      {(showAdd || editing) && (
        <WorkspaceDialog
          workspace={editing}
          onClose={() => { setShowAdd(false); setEditing(null) }}
          onSaved={() => { setShowAdd(false); setEditing(null); load() }}
        />
      )}
    </Card>
  )
}

// ── shared ───────────────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--mut)' }}>{label}</label>
      {children}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line2)',
  background: 'var(--card2)', color: 'var(--ink)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
}

export default SettingsPage
