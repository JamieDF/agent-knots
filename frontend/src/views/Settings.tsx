import { useEffect, useState, useCallback, useRef, useLayoutEffect } from 'react'
import { useLocation } from 'react-router-dom'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip, Toggle, SectionLabel, Dialog, Field, inputStyle } from '../components/primitives'
import WorkspaceDialog from '../components/WorkspaceDialog'
import ConfirmDialog from '../components/ConfirmDialog'
import {
  fetchSettings, addProvider, deleteProvider, setDefaultProvider, saveIntegrations,
  fetchUsage, fetchPolicies, updatePolicy,
  fetchMcpServers, addMcpServer, toggleMcpServer, deleteMcpServer,
  fetchTools, createTool, deleteTool, toggleTool,
  fetchWorkspaces, deleteWorkspace, updateWorkspace,
  fetchVaultStatus, unlockVault, lockVault,
  fetchCredentials, addCredential, deleteCredential, fetchAuditLog,
  type ProviderInfo, type IntegrationsInfo, type UsageSummary, type PolicyInfo,
  type McpServerInfo, type ToolInfo, type Workspace, type CredentialInfo, type AuditEntryInfo,
} from '../lib/api'
import { PROVIDER_PRESETS } from '../lib/providerPresets'
import { timeAgo } from '../lib/format'
import { useAccessibility, FONT_FAMILIES, FONT_SCALES, type FontFamilyKey, type FontScale } from '../theme/AccessibilityContext'

const SECTIONS = [
  { id: 'usage', label: 'Usage' },
  { id: 'accessibility', label: 'Accessibility' },
  { id: 'providers', label: 'Model providers' },
  { id: 'tools', label: 'Tools' },
  { id: 'policies', label: 'Policies' },
  { id: 'mcp', label: 'MCP servers' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'vault', label: 'Vault' },
  { id: 'workspaces', label: 'Workspaces' },
]

/** Settings screen — a scrolling column of cards (one per SECTIONS
 * entry), in the order specified by design_handoff_atelier_cockpit/
 * README.md §8, with a sticky side nav for jumping between them
 * directly since the page has grown long enough that scrolling to a
 * specific card by hand is tedious. First-run flow previews (README
 * item 8) are deferred to Phase 6, which is what actually builds the
 * setup-wizard route these would link to. */
function SettingsPage() {
  const location = useLocation()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [activeId, setActiveId] = useState(SECTIONS[0].id)

  const scrollToSection = useCallback((id: string, smooth = true) => {
    const el = document.getElementById(id)
    el?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' })
  }, [])

  // Land on the right section when arriving via a #hash (bookmark, or
  // the /vault -> /settings#vault redirect for the old standalone route).
  // Every card fetches its own data on mount, so the page's layout keeps
  // shifting for a beat after first paint — one scrollIntoView right away
  // gets shoved out from under itself as later cards finish loading and
  // grow taller. Re-correct a few times as things settle instead of once.
  useLayoutEffect(() => {
    const id = location.hash.replace(/^#/, '')
    if (id && SECTIONS.some(s => s.id === id)) {
      setActiveId(id)
      const timers = [0, 150, 400, 900].map(delay =>
        window.setTimeout(() => scrollToSection(id, false), delay)
      )
      return () => timers.forEach(clearTimeout)
    }
    // Only on mount / hash change — not on every scroll-driven activeId update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.hash])

  // Scroll-spy: whichever section's top has crossed closest above the
  // container's top edge is the "current" one.
  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    let raf = 0
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const containerTop = container.getBoundingClientRect().top
        let current = SECTIONS[0].id
        for (const s of SECTIONS) {
          const el = document.getElementById(s.id)
          if (!el) continue
          if (el.getBoundingClientRect().top - containerTop <= 80) current = s.id
        }
        setActiveId(current)
      })
    }
    container.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => { container.removeEventListener('scroll', onScroll); cancelAnimationFrame(raf) }
  }, [])

  return (
    <DeskLayout width={1040} ref={scrollRef}>
      <div style={{ display: 'flex', gap: 28, alignItems: 'flex-start' }}>
        <nav style={{ position: 'sticky', top: 0, width: 150, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {SECTIONS.map(s => (
            <button
              key={s.id}
              onClick={() => scrollToSection(s.id)}
              style={{
                textAlign: 'left', padding: '6px 10px', borderRadius: 8, fontSize: 12.5, fontWeight: 600,
                color: activeId === s.id ? 'var(--acc)' : 'var(--ink2)',
                background: activeId === s.id ? 'var(--acc-soft)' : 'transparent',
              }}
            >
              {s.label}
            </button>
          ))}
        </nav>

        <div style={{ flex: 1, minWidth: 0, maxWidth: 800 }}>
          <Section id="usage"><UsageCard /></Section>
          <Section id="accessibility"><AccessibilityCard /></Section>
          <Section id="providers"><ProvidersCard /></Section>
          <Section id="tools"><ToolsCard /></Section>
          <Section id="policies"><PoliciesCard /></Section>
          <Section id="mcp"><McpServersCard /></Section>
          <Section id="integrations"><IntegrationsCard /></Section>
          <Section id="vault"><VaultCard /></Section>
          <Section id="workspaces" last><WorkspacesCard /></Section>
          {/* Without trailing space, a short last section (or two) can
              never scroll flush to the container's top — there just isn't
              enough content below it to push it up that far. That leaves
              the side nav's active-highlight visibly stuck on an earlier
              section whenever you jump to one of these. */}
          <div style={{ height: '70vh' }} />
        </div>
      </div>
    </DeskLayout>
  )
}

function Section({ id, last, children }: { id: string; last?: boolean; children: React.ReactNode }) {
  return (
    <div id={id} style={{ scrollMarginTop: 16, marginBottom: last ? 0 : 16 }}>
      {children}
    </div>
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
    <Card>
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

// ── 2. Accessibility ─────────────────────────────────────────────────────────

const FONT_SCALE_LABELS: Record<FontScale, string> = {
  0.875: 'Small',
  1: 'Default',
  1.125: 'Large',
  1.25: 'Larger',
  1.375: 'Largest',
}

function AccessibilityCard() {
  const { fontScale, setFontScale, fontFamily, setFontFamily } = useAccessibility()

  return (
    <Card>
      <SectionLabel>Accessibility</SectionLabel>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', margin: '4px 0 14px' }}>
        Applies everywhere in the app, saved to this browser.
      </div>

      <Field label="Text size">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {FONT_SCALES.map(scale => (
            <button
              key={scale}
              onClick={() => setFontScale(scale)}
              style={{
                padding: '6px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600,
                background: fontScale === scale ? 'var(--acc)' : 'var(--card2)',
                color: fontScale === scale ? 'var(--acc-ink)' : 'var(--ink2)',
              }}
            >
              {FONT_SCALE_LABELS[scale]}
            </button>
          ))}
        </div>
      </Field>

      <div style={{ height: 14 }} />

      <Field label="Font">
        <select
          aria-label="Font family"
          value={fontFamily}
          onChange={e => setFontFamily(e.target.value as FontFamilyKey)}
          style={inputStyle}
        >
          {(Object.keys(FONT_FAMILIES) as FontFamilyKey[]).map(key => (
            <option key={key} value={key}>{FONT_FAMILIES[key].label}</option>
          ))}
        </select>
      </Field>
    </Card>
  )
}

// ── 3. Model providers ───────────────────────────────────────────────────────

function ProvidersCard() {
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

// ── 4. Tools ─────────────────────────────────────────────────────────────────

function ToolsCard() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const load = useCallback(() => { fetchTools().then(d => setTools(d.tools)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Tools</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={accentTextBtnStyle({ marginLeft: 'auto' })}>+ Custom tool</button>
      </div>
      {tools.map(t => (
        <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--ink)', minWidth: 120 }}>{t.name}</span>
          <span style={{ fontSize: 11.5, color: 'var(--mut)', flex: 1 }}>{t.description}</span>
          <Chip soft color={t.builtin ? 'var(--mut)' : 'var(--acc)'}>{t.builtin ? 'BUILT-IN' : 'CUSTOM'}</Chip>
          <Toggle checked={t.enabled} onChange={async () => { await toggleTool(t.name); load() }} />
          {!t.builtin && <button onClick={async () => { await deleteTool(t.name); load() }} style={deleteBtnStyle}>✕</button>}
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
  const close = () => { reset(); onClose() }

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
    <FormDialog
      open={open} onClose={close} title="+ Custom tool" width={460}
      onSave={handleSave} saveDisabled={!name.trim() || !command.trim()} saving={saving} error={error}
    >
      <Field label="Name"><input aria-label="Tool name" value={name} onChange={e => setName(e.target.value)} placeholder="run_tests" style={inputStyle} /></Field>
      <Field label="Description"><input aria-label="Tool description" value={description} onChange={e => setDescription(e.target.value)} placeholder="optional" style={inputStyle} /></Field>
      <Field label="Shell command"><input aria-label="Shell command" value={command} onChange={e => setCommand(e.target.value)} placeholder="pytest {path} -v" style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }} /></Field>
      <Field label="Params"><input aria-label="Params" value={params} onChange={e => setParams(e.target.value)} placeholder="path:string, verbose:boolean" style={inputStyle} /></Field>
    </FormDialog>
  )
}

// ── 5. Policies ──────────────────────────────────────────────────────────────

function PoliciesCard() {
  const [policies, setPolicies] = useState<PolicyInfo[]>([])
  const load = useCallback(() => { fetchPolicies().then(d => setPolicies(d.policies)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  return (
    <Card>
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

// ── 6. MCP servers ───────────────────────────────────────────────────────────

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
    <Card>
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
          <button onClick={async () => { await deleteMcpServer(s.name); load() }} style={deleteBtnStyle}>✕</button>
        </div>
      ))}
      {showAdd ? (
        <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
          <input aria-label="MCP server name" value={name} onChange={e => setName(e.target.value)} placeholder="filesystem" style={{ ...inputStyle, flex: 1 }} />
          <input aria-label="MCP server URL" value={url} onChange={e => setUrl(e.target.value)} placeholder="stdio://..." style={{ ...inputStyle, flex: 1 }} />
          <button onClick={handleAdd} style={{ fontSize: 12, fontWeight: 600, color: 'var(--acc-ink)', background: 'var(--acc)', padding: '6px 12px', borderRadius: 8, whiteSpace: 'nowrap' }}>Add</button>
        </div>
      ) : (
        <button onClick={() => setShowAdd(true)} style={accentTextBtnStyle({ marginTop: 10 })}>+ Add MCP server</button>
      )}
    </Card>
  )
}

// ── 7. Integrations ──────────────────────────────────────────────────────────

function IntegrationsCard() {
  const [integrations, setIntegrations] = useState<IntegrationsInfo | null>(null)
  useEffect(() => { fetchSettings().then(s => setIntegrations(s.integrations)).catch(() => {}) }, [])

  if (!integrations) return null

  const update = async (patch: Partial<IntegrationsInfo>) => {
    setIntegrations(prev => prev ? { ...prev, ...patch } : prev)
    await saveIntegrations(patch)
  }

  return (
    <Card>
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

// ── 8. Vault ─────────────────────────────────────────────────────────────────

/** VaultStore's AuditEntry has no explicit action field — every
 * successful call (add, use) logs the same shape, distinguished only
 * by whether a command/template was involved. This is a best-effort
 * label from what's actually determinable, not a literal action enum. */
function auditAction(e: { success: boolean; command: string }): { label: string; color: string } {
  if (!e.success) return { label: 'ERROR', color: 'var(--err)' }
  if (e.command) return { label: 'INJECT', color: 'var(--acc)' }
  return { label: 'ACCESS', color: 'var(--warn-ink)' }
}

function templateChips(c: CredentialInfo): string[] {
  const chips: string[] = []
  for (const t of c.templates) {
    for (const key of Object.keys(t.env)) chips.push(`env:${key}`)
    if (t.file_path) chips.push(`file:${t.file_path}`)
    if (t.command_wrapper) chips.push('wrapper')
  }
  return chips
}

/** Vault card — locked/unlocked states, credentials list, audit log.
 * Values never reach this component; the API only ever returns
 * metadata. Folded into Settings (was its own top-nav screen) since
 * it's just more config, per README.md §7. */
function VaultCard() {
  const [lockState, setLockState] = useState<'locked' | 'unlocked' | 'uninitialized' | null>(null)
  const [passphrase, setPassphrase] = useState('')
  const [unlockError, setUnlockError] = useState('')
  const [unlocking, setUnlocking] = useState(false)

  const [credentials, setCredentials] = useState<CredentialInfo[]>([])
  const [audit, setAudit] = useState<AuditEntryInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const loadStatus = useCallback(async () => {
    const s = await fetchVaultStatus()
    setLockState(s.lock_state)
    return s.lock_state
  }, [])

  const loadUnlockedData = useCallback(async () => {
    const [c, a] = await Promise.all([fetchCredentials(), fetchAuditLog()])
    setCredentials(c.credentials)
    setAudit(a.entries)
  }, [])

  useEffect(() => {
    loadStatus().then(state => { if (state === 'unlocked') loadUnlockedData() })
  }, [loadStatus, loadUnlockedData])

  const handleUnlock = async () => {
    setUnlocking(true); setUnlockError('')
    try {
      await unlockVault(passphrase)
      setPassphrase('')
      await loadStatus()
      await loadUnlockedData()
    } catch (e) {
      setUnlockError(e instanceof Error ? e.message : 'Failed to unlock')
    } finally {
      setUnlocking(false)
    }
  }

  const handleLock = async () => {
    await lockVault()
    setCredentials([]); setAudit([])
    await loadStatus()
  }

  const handleDelete = async (id: string) => {
    await deleteCredential(id)
    loadUnlockedData()
  }

  if (lockState === null) return <Card><SectionLabel>Vault</SectionLabel></Card>

  if (lockState !== 'unlocked') {
    return (
      <Card>
        <SectionLabel>Vault</SectionLabel>
        <div style={{ textAlign: 'center', padding: '16px 0 4px' }}>
          <div style={{
            width: 52, height: 52, borderRadius: 14, background: 'var(--card2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, margin: '0 auto 14px',
          }}>🔒</div>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>
            {lockState === 'uninitialized' ? 'Set up the vault' : 'Vault is locked'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--mut)', marginBottom: 16 }}>
            AES-256-GCM encrypted credential store
          </div>
          <div style={{ maxWidth: 280, margin: '0 auto' }}>
            <input
              type="password"
              aria-label="Passphrase"
              value={passphrase}
              onChange={e => setPassphrase(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleUnlock()}
              placeholder="Passphrase"
              style={{ ...inputStyle, marginBottom: 12, textAlign: 'center' }}
              autoFocus
            />
            {unlockError && <div style={{ fontSize: 11.5, color: 'var(--err)', marginBottom: 10 }}>{unlockError}</div>}
            <button
              onClick={handleUnlock}
              disabled={unlocking || !passphrase}
              style={{
                width: '100%', padding: '9px 14px', borderRadius: 8, fontSize: 13, fontWeight: 700,
                background: 'var(--acc)', color: 'var(--acc-ink)', opacity: unlocking || !passphrase ? 0.6 : 1,
              }}
            >
              {unlocking ? 'Unlocking…' : lockState === 'uninitialized' ? 'Create vault' : 'Unlock vault'}
            </button>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <>
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <SectionLabel>Vault</SectionLabel>
          <Chip color="var(--ok)" soft>UNLOCKED</Chip>
          <button onClick={handleLock} style={accentTextBtnStyle()}>Lock</button>
          <div style={{ marginLeft: 'auto' }}>
            <button
              onClick={() => setShowAdd(true)}
              style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}
            >
              + Add credential
            </button>
          </div>
        </div>

        {credentials.length === 0 && (
          <div style={{ textAlign: 'center', padding: 16, color: 'var(--mut)', fontSize: 13 }}>No credentials yet.</div>
        )}

        {credentials.map(c => (
          <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderBottom: '1px solid var(--line)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--ink)', minWidth: 100 }}>{c.id}</span>
            <span style={{ fontSize: 11.5, color: 'var(--mut)', flex: 1 }}>{c.description}</span>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {templateChips(c).map((t, i) => <Chip key={i} mono>{t}</Chip>)}
            </div>
            <span style={{ fontSize: 10.5, color: 'var(--mut)', minWidth: 70, textAlign: 'right' }}>{timeAgo(c.last_used, 'never')}</span>
            <button onClick={() => handleDelete(c.id)} style={deleteBtnStyle}>✕</button>
          </div>
        ))}
      </Card>

      <Card>
        <div style={{ marginBottom: 10, fontSize: 13, fontWeight: 700 }}>Audit log</div>
        {audit.length === 0 && (
          <div style={{ textAlign: 'center', padding: 16, color: 'var(--mut)', fontSize: 13 }}>No activity yet.</div>
        )}
        {audit.map((e, i) => {
          const action = auditAction(e)
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 0', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>
              <span style={{ color: 'var(--mut)', minWidth: 130 }}>{new Date(e.timestamp * 1000).toLocaleString()}</span>
              <span style={{ color: action.color, fontWeight: 700, minWidth: 60 }}>{action.label}</span>
              <span style={{ color: 'var(--ink)', flex: 1 }}>{e.credential}</span>
              <span style={{ color: 'var(--mut)' }}>{e.caller}</span>
            </div>
          )
        })}
      </Card>

      <AddCredentialDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onSaved={() => { setShowAdd(false); loadUnlockedData() }}
      />
    </>
  )
}

function AddCredentialDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [id, setId] = useState('')
  const [description, setDescription] = useState('')
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const reset = () => { setId(''); setDescription(''); setValue(''); setError('') }
  const close = () => { reset(); onClose() }

  const handleSave = async () => {
    if (!id.trim() || !value) return
    setSaving(true); setError('')
    try {
      await addCredential({ id: id.trim(), description, value })
      reset()
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add credential')
    } finally {
      setSaving(false)
    }
  }

  return (
    <FormDialog
      open={open} onClose={close} title="+ Add credential" width={420}
      onSave={handleSave} saveDisabled={!id.trim() || !value} saving={saving} error={error}
    >
      <Field label="ID">
        <input aria-label="Credential ID" value={id} onChange={e => setId(e.target.value)} placeholder="github" style={inputStyle} />
      </Field>
      <Field label="Description">
        <input aria-label="Description" value={description} onChange={e => setDescription(e.target.value)} placeholder="optional" style={inputStyle} />
      </Field>
      <Field label="Value">
        <input aria-label="Credential value" type="password" value={value} onChange={e => setValue(e.target.value)} placeholder="ghp_xxx" style={inputStyle} />
      </Field>
    </FormDialog>
  )
}

// ── 9. Workspaces ────────────────────────────────────────────────────────────

function WorkspacesCard() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [editing, setEditing] = useState<Workspace | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null)

  const load = useCallback(() => { fetchWorkspaces(true).then(d => setWorkspaces(d.workspaces)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  const setArchived = async (id: string, archived: boolean) => { await updateWorkspace(id, { archived }); load() }
  const confirmDelete = async () => {
    if (!deleteTarget) return
    await deleteWorkspace(deleteTarget.id)
    setDeleteTarget(null)
    load()
  }

  const active = workspaces.filter(w => !w.archived)
  const archived = workspaces.filter(w => w.archived)

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Workspaces</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={accentTextBtnStyle({ marginLeft: 'auto' })}>+ Add workspace</button>
      </div>
      {active.length === 0 && (
        <div style={{ textAlign: 'center', padding: 12, color: 'var(--mut)', fontSize: 13 }}>No workspaces yet.</div>
      )}
      {active.map(w => (
        <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)', minWidth: 80 }}>{w.id}</span>
          <span style={{ fontSize: 13, color: 'var(--ink)', flex: 1 }}>{w.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>{w.repository || '—'}</span>
          <Chip mono soft>{w.runtime || 'global'}</Chip>
          <button onClick={() => setEditing(w)} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}>Edit</button>
          <button onClick={() => setArchived(w.id, true)} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--mut)' }}>Archive</button>
          <button onClick={() => setDeleteTarget(w)} style={deleteBtnStyle}>✕</button>
        </div>
      ))}

      {archived.length > 0 && (
        <>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--mut)', margin: '14px 0 4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Archived</div>
          {archived.map(w => (
            <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)', opacity: 0.6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)', minWidth: 80 }}>{w.id}</span>
              <span style={{ fontSize: 13, color: 'var(--ink)', flex: 1 }}>{w.name}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>{w.repository || '—'}</span>
              <button onClick={() => setArchived(w.id, false)} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}>Unarchive</button>
              <button onClick={() => setDeleteTarget(w)} style={deleteBtnStyle}>✕</button>
            </div>
          ))}
        </>
      )}

      {(showAdd || editing) && (
        <WorkspaceDialog
          workspace={editing}
          onClose={() => { setShowAdd(false); setEditing(null) }}
          onSaved={() => { setShowAdd(false); setEditing(null); load() }}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete this workspace?"
        message={deleteTarget ? `Delete workspace "${deleteTarget.name}"? This cannot be undone. Tasks already assigned to it are not deleted.` : ''}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </Card>
  )
}

// ── shared ───────────────────────────────────────────────────────────────────
// Field/inputStyle now live in components/primitives/Field.tsx — this
// file's own copies (byte-for-byte identical to five other dialog
// files' copies) were the last ones migrated over.

// The delete-"✕" and small accent-text ("+ Add X", "Lock") button
// styles were copy-pasted 6x/5x across this file's section cards —
// AgentThread.tsx already extracted an equivalent pillBtn() helper for
// the same problem, this file never got the same treatment.
const deleteBtnStyle: React.CSSProperties = { color: 'var(--err)', fontSize: 14 }
function accentTextBtnStyle(extra?: React.CSSProperties): React.CSSProperties {
  return { fontSize: 12, fontWeight: 600, color: 'var(--acc)', ...extra }
}

// AddProviderDialog/CustomToolDialog/AddCredentialDialog were three
// near-identical "title + Field stack + error + Cancel/Save footer"
// dialogs, differing only in their fields and one preset-chips row
// (AddProviderDialog only, passed via headerExtra). Each dialog still
// owns its own field state and save logic — only the wrapper chrome
// (title, error slot, footer buttons, saving/disabled states) is shared.
function FormDialog({
  open, onClose, title, width = 440, headerExtra, children,
  onSave, saveDisabled, saving, error, saveLabel = 'Add', savingLabel = 'Adding…',
}: {
  open: boolean
  onClose: () => void
  title: string
  width?: number
  headerExtra?: React.ReactNode
  children: React.ReactNode
  onSave: () => void
  saveDisabled?: boolean
  saving: boolean
  error: string
  saveLabel?: string
  savingLabel?: string
}) {
  return (
    <Dialog open={open} onClose={onClose} width={width}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>{title}</div>
      {headerExtra}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {children}
        {error && <div style={{ fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={onSave} disabled={saving || saveDisabled} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || saveDisabled ? 0.6 : 1 }}>
            {saving ? savingLabel : saveLabel}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

export default SettingsPage
