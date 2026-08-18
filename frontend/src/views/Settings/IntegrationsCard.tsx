import { useEffect, useState } from 'react'
import { Card, SectionLabel, Toggle } from '../../components/primitives'
import { fetchSettings, saveIntegrations, type IntegrationsInfo } from '../../lib/api'

export function IntegrationsCard() {
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
      {/* The GitHub toggle that used to sit here promised to open a PR
          when a task entered review, and did nothing. That behaviour is
          real now, but as a workspace setting rather than a global
          on/off — and it fires on approve, not on entering review,
          since the latter would publish work nobody had approved. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>GitHub pull requests</div>
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>
            Set per workspace under <a href="#workspaces" style={{ color: 'var(--acc)' }}>Workspaces</a> — choose
            whether finishing a task merges locally or opens a PR. Uses the <code style={{ fontFamily: 'var(--font-mono)' }}>gh</code> CLI.
          </div>
        </div>
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
