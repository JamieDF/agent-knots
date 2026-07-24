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
